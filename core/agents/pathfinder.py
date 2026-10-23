"""
Agent 0: Pathfinder - Personalized repository discovery and ranking.
"""
from typing import List, Optional, Dict
from datetime import datetime, timezone
import json
import re

from core.agents.base import BaseAgent
from core.schemas import (
    RankedRepo,
    RepoScoreBreakdown,
    RepoSearchPreferences,
    PathfinderOutput,
    PathfinderSearchMeta,
)
from core.memory.hindsight_client import get_scout_hindsight
from core.memory.repo_search_memory import (
    build_repo_search_recall_query,
    build_repo_search_retain_fact,
    repo_search_retain_metadata,
)
from core.memory.skipped_repos import (
    merge_exclude_sets,
    normalize_repo_id,
    repo_matches_exclude,
    skipped_ids_from_memories,
)
from core.runtime.groq_context import pipeline_user_id_var
from integrations.groq_client import GroqClient, MODEL_LLAMA_4_SCOUT_17B


class PathfinderAgent(BaseAgent):
    """
    Agent 0: Pathfinder
    
    Responsible for:
    - Searching GitHub for repositories matching the user's tech stack
    - Scoring repositories based on multiple criteria
    - Ranking and presenting top 5 repositories
    - Providing detailed information for user selection
    
    Weighted score (0-100):
    - active_score * 0.25 + beginner_friendly * 0.30 + tech_match * 0.20
      + issue_quality * 0.15 + community_score * 0.10
    """
    
    def __init__(
        self,
        groq_client: GroqClient,
        model: Optional[str] = None
    ):
        super().__init__(groq_client, model or MODEL_LLAMA_4_SCOUT_17B)
    
    @property
    def name(self) -> str:
        return "Pathfinder"
    
    @property
    def role_prompt(self) -> str:
        return """You are the Pathfinder agent, an expert at discovering open-source repositories tailored to each contributor.

Your role is to:
1. Interpret natural-language goals (tech stack, domain, difficulty, task type)
2. Find repositories with healthy activity, approachable issues, and strong onboarding
3. Explain clearly why each repository fits the user's stated preferences

Prioritize recent maintenance, good-first issues, README/contributing clarity, stack alignment, labeled issues, and welcoming communities."""
    
    def run(
        self,
        tech_stack: Optional[List[str]] = None,
        github_client=None,
        top_n: int = 5,
        client_request_id: str = "",
        exclude_repo_urls: Optional[List[str]] = None,
        search_prompt: str = "",
    ) -> PathfinderOutput:
        """
        Search and rank repositories from tech tags and/or a natural-language prompt.

        Args:
            tech_stack: Optional list of technologies (merged with parsed prompt)
            search_prompt: Free-text description of desired repositories
            github_client: GitHub API client instance
            top_n: Number of top repositories to return

        Returns:
            PathfinderOutput with ranked repositories
        """
        self.activate_agent_llm_context()
        self._llm_personalization_calls = 0
        prompt_text = (search_prompt or "").strip()
        tag_stack = [t.strip() for t in (tech_stack or []) if t and t.strip()]

        preferences = self._resolve_preferences(prompt_text, tag_stack)
        effective_stack = preferences.tech_stack
        self.log(
            f"Searching repos — stack: {', '.join(effective_stack) or 'any'}; "
            f"domain: {preferences.domain or 'any'}; difficulty: {preferences.difficulty}"
        )

        recalled_memory_ids: list[str] = []
        memory_summary = ""
        user_memory_section = ""
        memories: list = []
        exclude_ids: set[str] = set()
        disliked_repos: list[dict[str, object]] = []
        uid = pipeline_user_id_var.get()
        if uid:
            try:
                hx = get_scout_hindsight()
                recall_query = build_repo_search_recall_query(prompt_text, preferences)
                memories = hx.recall_sync(
                    uid,
                    recall_query,
                    top_k=15,
                )
                recalled_memory_ids = [
                    str(m.get("memory_id") or "") for m in memories if m.get("memory_id")
                ]
                recalled_memory_ids = [x for x in recalled_memory_ids if x]
                exclude_ids = skipped_ids_from_memories(memories)
                disliked_repos = self._extract_disliked_repos(memories)
                if memories:
                    lines = "\n".join(f"- {(m.get('text') or '')[:400]}" for m in memories[:10])
                    user_memory_section = f"\n\n## What I know about this user\n{lines}\n"
                    memory_summary = (
                        f"Influenced by {len(recalled_memory_ids)} past memories about your preferences"
                    )
            except Exception as e:
                self.log(f"Hindsight recall skipped: {e}", level="warning")

        exclude_ids = merge_exclude_sets(exclude_repo_urls, exclude_ids)
        if exclude_ids:
            self.log(f"Excluding {len(exclude_ids)} skipped repositories from ranking")

        normalized_stack = [t.strip().lower() for t in effective_stack if t.strip()]

        if not normalized_stack and not (preferences.domain or "").strip():
            return self._finalize_output(
                effective_stack,
                [],
                [],
                recalled_memory_ids,
                memory_summary,
                repos_discovered=0,
                queries_run=0,
                client_request_id=client_request_id,
                search_prompt=prompt_text,
                preferences=preferences,
            )

        search_queries = self._generate_search_queries(preferences)
        
        # Search GitHub for repositories
        all_repos = []
        for query in search_queries[:5]:  # Limit to 5 queries
            try:
                repos = github_client.search_repos(query, per_page=10)
                all_repos.extend(repos)
            except Exception as e:
                self.log(f"Search failed for query '{query}': {e}", level="warning")
        
        # Deduplicate by full_name and drop user-skipped repos
        seen = set()
        unique_repos = []
        for repo in all_repos:
            if repo.full_name not in seen:
                seen.add(repo.full_name)
                if not repo_matches_exclude(repo, exclude_ids):
                    unique_repos.append(repo)
        
        self.log(f"Found {len(unique_repos)} unique repositories (after skip filter)")
        
        if not unique_repos:
            return self._finalize_output(
                effective_stack,
                [],
                search_queries,
                recalled_memory_ids,
                memory_summary,
                repos_discovered=0,
                queries_run=min(len(search_queries), 5),
                client_request_id=client_request_id,
                search_prompt=prompt_text,
                preferences=preferences,
            )

        ranked_repos = self._score_and_rank_repos(
            unique_repos,
            preferences,
            github_client,
            top_n,
            user_memory_section,
            disliked_repos,
        )

        return self._finalize_output(
            effective_stack,
            ranked_repos,
            search_queries,
            recalled_memory_ids,
            memory_summary,
            repos_discovered=len(unique_repos),
            queries_run=min(len(search_queries), 5),
            client_request_id=client_request_id,
            search_prompt=prompt_text,
            preferences=preferences,
        )

    def _finalize_output(
        self,
        tech_stack: List[str],
        ranked_repos: List[RankedRepo],
        search_queries: List[str],
        recalled_memory_ids: List[str],
        memory_summary: str,
        *,
        repos_discovered: int,
        queries_run: int,
        client_request_id: str,
        search_prompt: str = "",
        preferences: Optional[RepoSearchPreferences] = None,
    ) -> PathfinderOutput:
        self._retain_search_preferences(
            search_prompt,
            preferences,
            len(ranked_repos),
        )
        return PathfinderOutput(
            tech_stack=tech_stack,
            search_prompt=search_prompt,
            preferences=preferences,
            ranked_repos=ranked_repos,
            search_queries_used=search_queries,
            recalled_memory_ids=recalled_memory_ids,
            memory_summary=memory_summary,
            search_meta=PathfinderSearchMeta(
                repos_discovered=repos_discovered,
                search_queries_run=queries_run,
                llm_personalization_calls=getattr(self, "_llm_personalization_calls", 0),
                generated_at=datetime.now(timezone.utc).isoformat(),
                client_request_id=client_request_id or "",
            ),
        )

    def _retain_search_preferences(
        self,
        search_prompt: str,
        preferences: Optional[RepoSearchPreferences],
        ranked_count: int,
    ) -> None:
        """Store completed search preferences in Hindsight for future recall."""
        if not preferences:
            return
        has_signal = bool(
            (search_prompt or "").strip()
            or preferences.tech_stack
            or (preferences.domain or "").strip()
            or preferences.preferred_tasks
        )
        if not has_signal:
            return
        uid = pipeline_user_id_var.get()
        if not uid:
            return
        try:
            hx = get_scout_hindsight()
            hx.retain_sync(
                uid,
                build_repo_search_retain_fact(
                    search_prompt, preferences, ranked_count=ranked_count
                ),
                "experience",
                repo_search_retain_metadata(
                    search_prompt, preferences, ranked_count=ranked_count
                ),
            )
        except Exception as e:
            self.log(f"Hindsight retain for repo search skipped: {e}", level="warning")

    def _resolve_preferences(
        self, search_prompt: str, tag_stack: List[str]
    ) -> RepoSearchPreferences:
        if search_prompt:
            parsed = self._parse_search_preferences(search_prompt)
            merged_stack = list(dict.fromkeys(tag_stack + parsed.tech_stack))
            domain = (parsed.domain or "").strip()
            if not merged_stack and not domain:
                # Neither a known tech nor a recognized domain was extracted
                # (e.g. "CRM", "fintech") — fall back to the raw term so the
                # search still runs instead of returning zero results.
                domain = search_prompt.strip().lower()[:60]
            return RepoSearchPreferences(
                tech_stack=merged_stack,
                domain=domain,
                difficulty=parsed.difficulty or "beginner",
                preferred_tasks=parsed.preferred_tasks,
            )
        return self._preferences_from_tags(tag_stack)

    def _preferences_from_tags(self, tag_stack: List[str]) -> RepoSearchPreferences:
        return RepoSearchPreferences(
            tech_stack=tag_stack,
            domain="",
            difficulty="beginner",
            preferred_tasks=[],
        )

    def _parse_search_preferences(self, search_prompt: str) -> RepoSearchPreferences:
        """Convert natural-language prompt to structured search preferences via LLM."""
        try:
            prompt = f"""Extract structured open-source repository search preferences from the user message.

User message:
{search_prompt}

Respond with JSON only:
{{
  "tech_stack": ["React", "Node.js"],
  "domain": "AI",
  "difficulty": "beginner",
  "preferred_tasks": ["frontend"]
}}

Rules:
- tech_stack: concrete languages/frameworks mentioned (empty array if none)
- domain: short topic area (AI, web, mobile, devtools, data, etc.) or empty string
- difficulty: one of beginner, intermediate, advanced (default beginner)
- preferred_tasks: areas like frontend, backend, docs, testing, devops (empty if unclear)"""

            response = self.groq.complete(
                prompt=prompt,
                model=self.model,
                system_prompt=self.role_prompt,
                temperature=0.1,
                max_tokens=250,
                agent_name=self.name,
            )
            self._llm_personalization_calls = getattr(self, "_llm_personalization_calls", 0) + 1

            json_match = re.search(r"\{[\s\S]*\}", response)
            if json_match:
                data = json.loads(json_match.group())
                return RepoSearchPreferences(
                    tech_stack=[str(t).strip() for t in data.get("tech_stack", []) if str(t).strip()],
                    domain=str(data.get("domain") or "").strip(),
                    difficulty=str(data.get("difficulty") or "beginner").strip().lower(),
                    preferred_tasks=[
                        str(t).strip().lower()
                        for t in data.get("preferred_tasks", [])
                        if str(t).strip()
                    ],
                )
        except Exception as e:
            self.log(f"Preference parsing failed, using heuristics: {e}", level="warning")

        return self._heuristic_preferences(search_prompt)

    def _heuristic_preferences(self, text: str) -> RepoSearchPreferences:
        """Fallback keyword extraction when LLM parsing fails."""
        lower = text.lower()
        tech_hints = []
        known = [
            "python", "javascript", "typescript", "react", "node.js", "nodejs",
            "go", "golang", "rust", "java", "vue", "angular", "django", "flask",
            "fastapi", "next.js", "nextjs", "c++", "csharp", "c#", "ruby", "php",
        ]
        for name in known:
            if name in lower:
                tech_hints.append(name.title() if name != "nodejs" else "Node.js")

        domain = ""
        for key, label in [
            ("machine learning", "AI"), (" ai ", "AI"), ("artificial intelligence", "AI"),
            ("web", "web"), ("mobile", "mobile"), ("devtools", "devtools"),
            ("data", "data"), ("game", "gaming"),
        ]:
            if key in lower:
                domain = label
                break

        difficulty = "beginner"
        if "advanced" in lower or "expert" in lower:
            difficulty = "advanced"
        elif "intermediate" in lower:
            difficulty = "intermediate"

        tasks = []
        for task in ("frontend", "backend", "docs", "documentation", "testing", "devops"):
            if task in lower:
                tasks.append("docs" if task == "documentation" else task)

        return RepoSearchPreferences(
            tech_stack=tech_hints,
            domain=domain,
            difficulty=difficulty,
            preferred_tasks=tasks,
        )

    def _generate_search_queries(self, preferences: RepoSearchPreferences) -> List[str]:
        """Generate GitHub search queries from structured preferences."""
        tech_stack = [t.strip().lower() for t in preferences.tech_stack if t.strip()]
        queries = []

        tech_mappings = {
            'python': 'language:python',
            'javascript': 'language:javascript',
            'js': 'language:javascript',
            'typescript': 'language:typescript',
            'ts': 'language:typescript',
            'java': 'language:java',
            'go': 'language:go',
            'golang': 'language:go',
            'rust': 'language:rust',
            'c++': 'language:cpp',
            'cpp': 'language:cpp',
            'c#': 'language:csharp',
            'csharp': 'language:csharp',
            'ruby': 'language:ruby',
            'php': 'language:php',
            'swift': 'language:swift',
            'kotlin': 'language:kotlin',
            'react': 'react language:javascript',
            'reactjs': 'react language:javascript',
            'vue': 'vue language:javascript',
            'vuejs': 'vue language:javascript',
            'angular': 'angular language:typescript',
            'node': 'nodejs language:javascript',
            'nodejs': 'nodejs language:javascript',
            'express': 'express language:javascript',
            'django': 'django language:python',
            'flask': 'flask language:python',
            'fastapi': 'fastapi language:python',
            'spring': 'spring language:java',
            'rails': 'rails language:ruby',
            'laravel': 'laravel language:php',
        }
        
        difficulty = (preferences.difficulty or "beginner").lower()
        gfi_filter = "good-first-issues:>3" if difficulty != "advanced" else "help-wanted-issues:>1"
        star_floor = "stars:>50" if difficulty == "beginner" else "stars:>200"

        domain_queries = self._domain_search_terms(preferences.domain)
        task_queries = self._task_search_terms(preferences.preferred_tasks)

        for tech in tech_stack:
            tech_lower = tech.lower()
            base = tech_mappings.get(tech_lower, tech)
            queries.append(f"{base} {gfi_filter} {star_floor}")
            for domain_q in domain_queries[:1]:
                queries.append(f"{base} {domain_q} {gfi_filter} {star_floor}")
            for task_q in task_queries[:1]:
                queries.append(f"{base} {task_q} {gfi_filter}")

        if len(tech_stack) >= 2:
            combined = " ".join(tech_mappings.get(t, t) for t in tech_stack[:2])
            queries.append(f"{combined} {gfi_filter} {star_floor}")

        if not tech_stack and domain_queries:
            for domain_q in domain_queries[:3]:
                queries.append(f"{domain_q} {gfi_filter} {star_floor}")

        if not tech_stack and not domain_queries and task_queries:
            for task_q in task_queries[:2]:
                queries.append(f"{task_q} {gfi_filter} {star_floor}")

        seen_q: set[str] = set()
        unique: list[str] = []
        for q in queries:
            q_norm = " ".join(q.split())
            if q_norm not in seen_q:
                seen_q.add(q_norm)
                unique.append(q_norm)
        return unique[:8]

    def _domain_search_terms(self, domain: str) -> List[str]:
        d = (domain or "").strip().lower()
        mapping = {
            "ai": ["topic:machine-learning", "topic:deep-learning", "artificial-intelligence"],
            "web": ["topic:web", "topic:frontend"],
            "mobile": ["topic:android", "topic:ios"],
            "data": ["topic:data-science", "topic:analytics"],
            "devtools": ["topic:developer-tools", "topic:cli"],
            "gaming": ["topic:game", "topic:gamedev"],
        }
        return mapping.get(d, [d] if d else [])

    def _task_search_terms(self, tasks: List[str]) -> List[str]:
        mapping = {
            "frontend": ["topic:frontend", "topic:react", "topic:vue"],
            "backend": ["topic:backend", "topic:api"],
            "docs": ["topic:documentation", "topic:docs"],
            "testing": ["topic:testing", "topic:test"],
            "devops": ["topic:devops", "topic:docker"],
        }
        terms: list[str] = []
        for task in tasks:
            terms.extend(mapping.get(task.lower(), []))
        return terms
    
    def _score_and_rank_repos(
        self,
        repos: list,
        preferences: RepoSearchPreferences,
        github_client,
        top_n: int,
        user_memory_section: str = "",
        disliked_repos: Optional[list[dict[str, object]]] = None,
    ) -> List[RankedRepo]:
        """Score repositories and return top N ranked."""
        scored_repos = []
        user_stack = [t.strip().lower() for t in preferences.tech_stack if t.strip()]

        for repo in repos:
            try:
                score_result = self._calculate_repo_score(repo, preferences, github_client)
                penalty = self._repo_dislike_penalty(repo, disliked_repos or [])
                if penalty:
                    score_result = dict(score_result)
                    score_result["total"] = max(0, score_result["total"] - penalty)
                scored_repos.append((repo, score_result))
            except Exception as e:
                self.log(f"Failed to score {repo.full_name}: {e}", level="warning")

        scored_repos.sort(key=lambda x: x[1]["total"], reverse=True)

        ranked = []
        for repo, score_result in scored_repos[:top_n]:
            why_match = self._generate_match_reasons(
                repo, preferences, score_result, user_memory_section
            )
            ranked.append(
                RankedRepo(
                    full_name=repo.full_name,
                    url=repo.html_url,
                    description=repo.description or "No description available",
                    language=repo.language,
                    stars=repo.stargazers_count,
                    open_issues=repo.open_issues_count,
                    score_total=score_result["total"],
                    score_breakdown=RepoScoreBreakdown(
                        active_score=score_result["active_score"],
                        beginner_friendly=score_result["beginner_friendly"],
                        tech_match=score_result["tech_match"],
                        issue_quality=score_result["issue_quality"],
                        community_score=score_result["community_score"],
                    ),
                    why_match=why_match,
                    topics=getattr(repo, "topics", []) or [],
                )
            )

        return ranked

    def _extract_disliked_repos(self, memories: list) -> list[dict[str, object]]:
        """Extract repo thumbs-down feedback from memories for ranking penalties."""
        disliked: list[dict[str, object]] = []
        for m in memories or []:
            meta = m.get("metadata") if isinstance(m.get("metadata"), dict) else {}
            if (meta.get("kind") or "").lower() != "thumbs":
                continue
            if (meta.get("vote") or "").lower() != "down":
                continue
            if (meta.get("target_type") or "").lower() != "repo":
                continue
            repo_url = meta.get("repo_url") or meta.get("target_id") or ""
            repo_id = normalize_repo_id(repo_url or meta.get("repo_full_name") or "")
            if not repo_id:
                continue
            language = (meta.get("language") or "").strip().lower()
            topics = [
                str(t).strip().lower()
                for t in (meta.get("topics") or [])
                if str(t).strip()
            ]
            disliked.append({
                "id": repo_id,
                "language": language,
                "topics": set(topics),
            })
        return disliked

    def _repo_dislike_penalty(self, repo, disliked_repos: list[dict[str, object]]) -> int:
        if not disliked_repos:
            return 0
        repo_id = normalize_repo_id(getattr(repo, "html_url", "") or getattr(repo, "full_name", ""))
        language = (getattr(repo, "language", "") or "").strip().lower()
        topics = {t.lower() for t in getattr(repo, "topics", []) or []}
        penalty = 0
        for disliked in disliked_repos:
            if repo_id and disliked.get("id") == repo_id:
                return 40
            if language and disliked.get("language") == language:
                penalty += 8
            disliked_topics = disliked.get("topics") or set()
            if topics and disliked_topics and topics.intersection(disliked_topics):
                penalty += 6
        return min(penalty, 20)
    
    def _calculate_repo_score(
        self,
        repo,
        preferences: RepoSearchPreferences,
        github_client,
    ) -> Dict[str, int]:
        """Score a repository on five 0-100 metrics, then apply weighted total."""
        user_stack = [t.strip().lower() for t in preferences.tech_stack if t.strip()]
        repo_language = (repo.language or "").lower()
        repo_languages = {k.lower(): v for k, v in getattr(repo, "languages", {}).items()}
        repo_topics = [t.lower() for t in getattr(repo, "topics", []) or []]
        desc_lower = (repo.description or "").lower()

        scores: Dict[str, int] = {
            "active_score": self._score_activity(repo),
            "beginner_friendly": self._score_beginner_friendly(
                repo, repo_topics, preferences.difficulty
            ),
            "tech_match": self._score_tech_match(
                repo,
                user_stack,
                repo_language,
                repo_languages,
                repo_topics,
                desc_lower,
                preferences,
            ),
            "issue_quality": self._score_issue_quality(repo, repo_topics),
            "community_score": self._score_community(repo),
            "total": 0,
        }

        scores["total"] = round(
            scores["active_score"] * 0.25
            + scores["beginner_friendly"] * 0.30
            + scores["tech_match"] * 0.20
            + scores["issue_quality"] * 0.15
            + scores["community_score"] * 0.10
        )
        return scores

    def _days_since_iso(self, iso_value: Optional[str]) -> Optional[int]:
        if not iso_value:
            return None
        try:
            normalized = iso_value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).days
        except (ValueError, TypeError):
            return None

    def _score_activity(self, repo) -> int:
        """Recent commits / maintenance — pushed_at and update recency."""
        score = 0
        days_push = self._days_since_iso(getattr(repo, "pushed_at", None))
        days_update = self._days_since_iso(getattr(repo, "updated_at", None))
        recency_days = days_push if days_push is not None else days_update

        if recency_days is not None:
            if recency_days <= 14:
                score += 55
            elif recency_days <= 30:
                score += 45
            elif recency_days <= 90:
                score += 30
            elif recency_days <= 180:
                score += 15
        else:
            if repo.stargazers_count > 500:
                score += 25
            elif repo.stargazers_count > 100:
                score += 15

        if 1 <= repo.open_issues_count <= 300:
            score += 20
        if repo.stargazers_count >= 200:
            score += 15
        if getattr(repo, "license_spdx", None):
            score += 10
        return min(score, 100)

    def _score_beginner_friendly(
        self, repo, repo_topics: List[str], difficulty: str
    ) -> int:
        """Good first issues, README/onboarding signals, difficulty fit."""
        score = 0
        beginner_topics = [
            "hacktoberfest",
            "good-first-issue",
            "good-first-issues",
            "beginner-friendly",
            "contributions-welcome",
            "first-timers-only",
        ]
        if any(bt in topic for topic in repo_topics for bt in beginner_topics):
            score += 35

        if repo.open_issues_count >= 10:
            score += 25
        elif repo.open_issues_count >= 5:
            score += 15
        elif repo.open_issues_count >= 1:
            score += 8

        desc = repo.description or ""
        if len(desc) >= 80:
            score += 15
        elif len(desc) >= 30:
            score += 8
        if getattr(repo, "has_wiki", False):
            score += 5

        diff = (difficulty or "beginner").lower()
        stars = repo.stargazers_count
        if diff == "beginner" and 100 <= stars <= 15000:
            score += 15
        elif diff == "intermediate" and stars >= 500:
            score += 12
        elif diff == "advanced" and stars >= 2000:
            score += 12

        return min(score, 100)

    def _score_tech_match(
        self,
        repo,
        user_stack: List[str],
        repo_language: str,
        repo_languages: dict,
        repo_topics: List[str],
        desc_lower: str,
        preferences: RepoSearchPreferences,
    ) -> int:
        """Stack, domain, and preferred task alignment."""
        if not user_stack and not preferences.domain and not preferences.preferred_tasks:
            return 50

        score = 0
        if user_stack:
            for tech in user_stack:
                if tech in repo_language or repo_language in tech:
                    score += 40
                    break
            secondary = 0
            for tech in user_stack:
                if tech in repo_languages:
                    secondary += 1
                if tech in repo_topics or any(tech in topic for topic in repo_topics):
                    secondary += 1
            score += min(secondary * 12, 35)

        domain = (preferences.domain or "").strip().lower()
        if domain:
            domain_terms = self._domain_search_terms(domain)
            domain_hit = any(
                term.replace("topic:", "") in " ".join(repo_topics)
                or term.replace("topic:", "") in desc_lower
                for term in domain_terms
            ) or domain in desc_lower
            if domain_hit:
                score += 25

        for task in preferences.preferred_tasks:
            task_terms = self._task_search_terms([task])
            if any(
                term.replace("topic:", "") in " ".join(repo_topics) or task in desc_lower
                for term in task_terms
            ):
                score += 12

        return min(score, 100)

    def _score_issue_quality(self, repo, repo_topics: List[str]) -> int:
        """Labeled, approachable issues and contribution clarity."""
        score = 0
        label_topics = ["help-wanted", "good-first-issue", "up-for-grabs", "contributions-welcome"]
        if any(lt in topic for topic in repo_topics for lt in label_topics):
            score += 40

        issues = repo.open_issues_count
        if 10 <= issues <= 100:
            score += 35
        elif 5 <= issues <= 200:
            score += 25
        elif issues > 0:
            score += 12

        if repo.description and ("contribut" in repo.description.lower() or "issue" in repo.description.lower()):
            score += 15
        return min(score, 100)

    def _score_community(self, repo) -> int:
        """Contributor proxy via stars and healthy issue discussion."""
        score = 0
        stars = repo.stargazers_count
        if stars >= 5000:
            score += 45
        elif stars >= 1000:
            score += 38
        elif stars >= 300:
            score += 28
        elif stars >= 50:
            score += 18
        elif stars >= 10:
            score += 8

        issues = repo.open_issues_count
        if 10 <= issues <= 150:
            score += 35
        elif 5 <= issues <= 250:
            score += 22
        elif issues > 0:
            score += 10

        if getattr(repo, "has_wiki", False):
            score += 10
        return min(score, 100)
    
    def _generate_match_reasons(
        self,
        repo,
        preferences: RepoSearchPreferences,
        score_result: dict,
        user_memory_section: str = "",
    ) -> List[str]:
        """Generate human-readable reasons why this repo matches the user."""
        try:
            prefs_json = preferences.model_dump()
            prompt = f"""Given this GitHub repository and the user's search preferences, provide 3-4 concise bullet points explaining why this is a good match.

Repository: {repo.full_name}
Description: {repo.description or 'No description'}
Primary Language: {repo.language or 'Unknown'}
Stars: {repo.stargazers_count}
Open Issues: {repo.open_issues_count}
Topics: {', '.join(getattr(repo, 'topics', []) or [])}

User preferences: {json.dumps(prefs_json)}
{user_memory_section}

Score Breakdown (each 0-100, weighted total {score_result['total']}/100):
- Activity: {score_result['active_score']}
- Beginner-friendly: {score_result['beginner_friendly']}
- Tech match: {score_result['tech_match']}
- Issue quality: {score_result['issue_quality']}
- Community: {score_result['community_score']}

Respond with JSON: {{"reasons": ["...", "..."]}}
Focus on stack/domain fit, beginner opportunities, recent activity, and issue clarity."""

            response = self.groq.complete(
                prompt=prompt,
                model=self.model,
                system_prompt=self.role_prompt,
                temperature=0.3,
                max_tokens=300,
                agent_name=self.name,
            )
            self._llm_personalization_calls = getattr(self, "_llm_personalization_calls", 0) + 1

            json_match = re.search(r'\{[^{}]*"reasons"[^{}]*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data.get("reasons", self._fallback_reasons(repo, preferences))

            return self._fallback_reasons(repo, preferences)

        except Exception as e:
            self.log(f"Failed to generate reasons: {e}", level="warning")
            return self._fallback_reasons(repo, preferences)

    def _fallback_reasons(self, repo, preferences: RepoSearchPreferences) -> List[str]:
        """Generate fallback reasons without LLM."""
        reasons = []
        stack_lower = [t.lower() for t in preferences.tech_stack]

        if repo.language:
            if repo.language.lower() in stack_lower:
                reasons.append(f"Uses {repo.language}, matching your tech stack")
            else:
                reasons.append(f"Primary language: {repo.language}")

        if preferences.domain:
            reasons.append(f"Aligns with your interest in {preferences.domain}")

        if repo.stargazers_count > 100:
            reasons.append(f"Active community ({repo.stargazers_count:,} stars)")

        if repo.open_issues_count > 0:
            reasons.append(f"{repo.open_issues_count} open issues to explore")

        pushed = getattr(repo, "pushed_at", None)
        if pushed:
            days = self._days_since_iso(pushed)
            if days is not None and days <= 30:
                reasons.append("Recently updated — maintainers are active")

        if not reasons:
            reasons.append("Potential contribution opportunity")

        return reasons[:4]
