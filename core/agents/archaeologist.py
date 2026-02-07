"""
Agent 2: Archaeologist - Code locator and tracer.
"""
from typing import List, Optional
from pathlib import Path
import json

from core.agents.base import BaseAgent
from core.schemas import GitHubIssue, Agent2Output, CodeHit
from integrations.groq_client import GroqClient
from utils.code_search import CodeSearcher
from utils.text_chunking import extract_keywords, truncate_to_tokens


class ArchaeologistAgent(BaseAgent):
    """
    Agent 2: Archaeologist
    
    Responsible for:
    - Extracting search keywords from issue
    - Searching codebase for relevant files
    - Identifying functions/classes to modify
    - Providing confidence score for findings
    """
    
    def __init__(
        self,
        groq_client: GroqClient,
        model: Optional[str] = None
    ):
        super().__init__(groq_client, model or "qwen-qwq-32b")
    
    @property
    def name(self) -> str:
        return "Archaeologist"
    
    @property
    def role_prompt(self) -> str:
        return """You are the Archaeologist agent, an expert at navigating and understanding codebases.

Your role is to:
1. Extract relevant keywords and patterns from issue descriptions
2. Identify which files, functions, and classes need modification
3. Trace code paths and dependencies
4. Provide confidence levels for your findings

Be thorough but focused. Prioritize precision over recall.
When uncertain, indicate lower confidence rather than guessing."""
    
    def run(
        self,
        issue: GitHubIssue,
        repo_path: Path,
        file_tree: List[str]
    ) -> Agent2Output:
        """
        Locate relevant code for an issue.
        
        Args:
            issue: The selected issue to analyze
            repo_path: Path to cloned repository
            file_tree: List of files in the repository
            
        Returns:
            Agent2Output with code locations
        """
        self.log(f"Searching codebase for issue #{issue.number}")
        
        # Initialize searcher
        searcher = CodeSearcher(repo_path)
        
        # Extract keywords from issue
        issue_text = f"{issue.title}\n{issue.body or ''}"
        keywords = extract_keywords(issue_text, max_keywords=10)
        
        self.log(f"Extracted keywords: {keywords}")
        
        # Get LLM to suggest search strategies
        search_strategies = self._get_search_strategy(issue, keywords, file_tree)
        
        # Perform searches
        all_results = []
        searched_queries = set()
        
        for query in search_strategies[:5]:  # Limit searches
            if query in searched_queries:
                continue
            searched_queries.add(query)
            
            results = searcher.search(
                query,
                max_results=10,
                case_sensitive=False
            )
            all_results.extend(results)
        
        # Deduplicate and group by file
        file_hits = {}
        for result in all_results:
            if result.file_path not in file_hits:
                file_hits[result.file_path] = {
                    "lines": [],
                    "matches": []
                }
            file_hits[result.file_path]["lines"].append(result.line_number)
            file_hits[result.file_path]["matches"].append(result.line_content)
        
        # Get top files and extract snippets
        hits = []
        sorted_files = sorted(
            file_hits.items(),
            key=lambda x: len(x[1]["lines"]),
            reverse=True
        )[:10]
        
        for file_path, data in sorted_files:
            # Get file content around matches
            min_line = max(1, min(data["lines"]) - 5)
            max_line = max(data["lines"]) + 10
            
            snippet = searcher.get_file_content(
                file_path,
                start_line=min_line,
                end_line=max_line,
                max_lines=100
            )
            
            # Extract symbols
            symbols = searcher.extract_symbols(file_path)
            
            hits.append(CodeHit(
                path=file_path,
                symbols=symbols[:10],
                snippet=truncate_to_tokens(snippet, 400),
                why_relevant=f"Contains {len(data['lines'])} matches for search terms"
            ))
        
        # Use LLM to analyze and enhance findings
        enhanced_output = self._analyze_findings(
            issue, hits, keywords, search_strategies
        )
        
        return enhanced_output
    
    def _get_search_strategy(
        self,
        issue: GitHubIssue,
        keywords: List[str],
        file_tree: List[str]
    ) -> List[str]:
        """Get LLM-suggested search queries."""
        try:
            # Sample file tree for context
            sample_files = file_tree[:50]
            
            prompt = f"""Given this GitHub issue and repository structure, suggest 5-8 specific search queries to find relevant code.

Issue #{issue.number}: {issue.title}

Description:
{(issue.body or "No description")[:800]}

Keywords extracted: {', '.join(keywords)}

Sample files in repo:
{chr(10).join(sample_files[:30])}

Respond with a JSON object containing a "queries" array of search terms/patterns to find the relevant code.
Include:
- Function/class names mentioned or implied
- Error messages or specific strings
- Variable/constant names
- File names or patterns

Example: {{"queries": ["handleSubmit", "ValidationError", "user_input", "form.py"]}}"""

            response = self.groq.complete(
                prompt=prompt,
                model=self.model,
                system_prompt=self.role_prompt,
                temperature=0.3,
                max_tokens=300,
                json_mode=True
            )
            
            data = json.loads(response)
            queries = data.get("queries", keywords)
            
            # Add original keywords as fallback
            queries.extend(keywords)
            
            return queries[:10]
        
        except Exception as e:
            self.log(f"Failed to get search strategy: {e}", level="warning")
            return keywords
    
    def _analyze_findings(
        self,
        issue: GitHubIssue,
        hits: List[CodeHit],
        keywords: List[str],
        strategies: List[str]
    ) -> Agent2Output:
        """Use LLM to analyze and enhance code findings."""
        try:
            # Build context for LLM
            hits_summary = ""
            for i, hit in enumerate(hits[:5], 1):
                hits_summary += f"\n{i}. {hit.path}\n"
                hits_summary += f"   Symbols: {', '.join(hit.symbols[:5])}\n"
                hits_summary += f"   Snippet preview:\n```\n{hit.snippet[:300]}\n```\n"
            
            prompt = f"""Analyze these code search results for issue #{issue.number}: "{issue.title}"

Issue description:
{(issue.body or "No description")[:600]}

Code locations found:
{hits_summary}

Based on this analysis, provide:
1. For each file hit, explain WHY it's relevant (be specific)
2. Suggest a call trace if you can infer one (A calls B calls C)
3. Rate your confidence: High (clear match), Medium (likely relevant), or Low (uncertain)
4. Suggest 2-3 additional files to check

Respond with JSON matching this structure:
{{
  "enhanced_hits": [
    {{"path": "...", "why_relevant": "specific explanation"}}
  ],
  "call_trace_hint": ["functionA", "functionB"],  
  "confidence": "High|Medium|Low",
  "next_files": ["file1.py", "file2.py"]
}}"""

            response = self.groq.complete(
                prompt=prompt,
                model=self.model,
                system_prompt=self.role_prompt,
                temperature=0.3,
                max_tokens=800,
                json_mode=True
            )
            
            data = json.loads(response)
            
            # Update hit explanations if provided
            enhanced_hits = data.get("enhanced_hits", [])
            for i, hit in enumerate(hits):
                if i < len(enhanced_hits):
                    hit.why_relevant = enhanced_hits[i].get("why_relevant", hit.why_relevant)
            
            return Agent2Output(
                issue_number=issue.number,
                keywords=keywords,
                search_strategy=strategies,
                hits=hits,
                call_trace_hint=data.get("call_trace_hint", []),
                confidence=data.get("confidence", "Medium"),
                next_files_to_check=data.get("next_files", [])
            )
        
        except Exception as e:
            self.log(f"Failed to analyze findings: {e}", level="warning")
            return Agent2Output(
                issue_number=issue.number,
                keywords=keywords,
                search_strategy=strategies,
                hits=hits,
                call_trace_hint=[],
                confidence="Medium",
                next_files_to_check=[]
            )
