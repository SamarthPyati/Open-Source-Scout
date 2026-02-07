"""
Agent 1: Triage Nurse - Issue ranking and selection.
"""
from typing import List, Optional
import json

from core.agents.base import BaseAgent
from core.schemas import (
    GitHubIssue, GitHubRepo, Agent1Output,
    RankedIssue, ScoreBreakdown, RepoInfo
)
from core.scoring import IssueScorer
from integrations.groq_client import GroqClient


class TriageNurseAgent(BaseAgent):
    """
    Agent 1: Triage Nurse
    
    Responsible for:
    - Fetching and filtering issues
    - Scoring issues based on beginner-friendliness
    - Ranking and selecting the best issue
    - Generating human-readable reasons for selection
    """
    
    def __init__(
        self,
        groq_client: GroqClient,
        model: Optional[str] = None
    ):
        super().__init__(groq_client, model or "qwen-qwq-32b")
        self.scorer = IssueScorer()
    
    @property
    def name(self) -> str:
        return "Triage Nurse"
    
    @property
    def role_prompt(self) -> str:
        return """You are the Triage Nurse agent, an expert at evaluating GitHub issues for beginner contributors.

Your role is to:
1. Analyze issue titles, descriptions, and labels
2. Identify issues suitable for first-time contributors
3. Provide clear, actionable reasons why each issue is good for beginners

Focus on:
- Clarity of requirements
- Scope appropriateness
- Available context and guidance
- Potential learning opportunities

Be encouraging but honest about difficulty levels."""
    
    def run(
        self,
        repo: GitHubRepo,
        issues: List[GitHubIssue],
        top_n: int = 3
    ) -> Agent1Output:
        """
        Rank issues and select the best one.
        
        Args:
            repo: Repository information
            issues: List of issues to rank
            top_n: Number of top issues to return
            
        Returns:
            Agent1Output with ranked issues
        """
        self.log(f"Analyzing {len(issues)} issues for {repo.full_name}")
        
        if not issues:
            # Return empty result if no issues
            return Agent1Output(
                repo=RepoInfo(
                    url=repo.html_url,
                    default_branch=repo.default_branch,
                    description=repo.description,
                    languages=list(repo.languages.keys())[:5] if repo.languages else None
                ),
                ranked_issues=[],
                selected_issue_number=0
            )
        
        # Score all issues
        ranked = self.scorer.rank_issues(issues, top_n=top_n)
        
        # Generate enhanced reasons using LLM
        ranked_issues = []
        for issue, score_result in ranked:
            # Get LLM to enhance the reasons
            enhanced_reasons = self._enhance_reasons(issue, score_result.reasons)
            
            ranked_issues.append(RankedIssue(
                number=issue.number,
                title=issue.title,
                url=issue.html_url,
                labels=issue.labels,
                score_total=score_result.total,
                score_breakdown=score_result.breakdown,
                why=enhanced_reasons
            ))
        
        # Select the top issue
        selected = ranked_issues[0].number if ranked_issues else 0
        
        self.log(f"Selected issue #{selected} with score {ranked_issues[0].score_total if ranked_issues else 0}")
        
        return Agent1Output(
            repo=RepoInfo(
                url=repo.html_url,
                default_branch=repo.default_branch,
                description=repo.description,
                languages=list(repo.languages.keys())[:5] if repo.languages else None
            ),
            ranked_issues=ranked_issues,
            selected_issue_number=selected
        )
    
    def _enhance_reasons(
        self,
        issue: GitHubIssue,
        base_reasons: List[str]
    ) -> List[str]:
        """Use LLM to enhance scoring reasons."""
        try:
            prompt = f"""Given this GitHub issue, provide 3-4 concise bullet points explaining why it's suitable for a beginner contributor.

Issue #{issue.number}: {issue.title}

Description:
{(issue.body or "No description")[:1000]}

Labels: {', '.join(issue.labels) if issue.labels else 'None'}

Base analysis notes:
{chr(10).join('- ' + r for r in base_reasons)}

Respond with a JSON object containing a "reasons" array of 3-4 short, specific bullet points. Each should be one sentence. Focus on actionability and encouragement.

Example format:
{{"reasons": ["Clear scope: single file change needed", "Good documentation in issue", "Active maintainer responses"]}}"""

            response = self.groq.complete(
                prompt=prompt,
                model=self.model,
                system_prompt=self.role_prompt,
                temperature=0.5,
                max_tokens=500,
                json_mode=True
            )
            
            data = json.loads(response)
            return data.get("reasons", base_reasons)[:4]
        
        except Exception as e:
            self.log(f"Failed to enhance reasons: {e}", level="warning")
            return base_reasons[:4]
