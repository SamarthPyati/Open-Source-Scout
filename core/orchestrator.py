"""
Orchestrator - Coordinates the 3-agent pipeline.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from core.agents.triage_nurse import TriageNurseAgent
from core.agents.archaeologist import ArchaeologistAgent
from core.agents.senior_dev import SeniorDevAgent
from core.schemas import (
    GitHubRepo, GitHubIssue, Agent1Output, Agent2Output, Agent3Output, RunLog
)
from integrations.github_client import GitHubClient
from integrations.groq_client import GroqClient
from utils.cache import CacheManager

logger = logging.getLogger(__name__)


class ScoutOrchestrator:
    """
    Orchestrates the 3-agent pipeline for issue analysis.
    
    Pipeline:
    1. Triage Nurse: Fetch and rank issues
    2. Archaeologist: Locate relevant code
    3. Senior Dev: Generate fix plan and PR draft
    """
    
    def __init__(
        self,
        github_client: GitHubClient,
        groq_client: GroqClient,
        cache_manager: Optional[CacheManager] = None,
        fast_model: str = "qwen-qwq-32b",
        powerful_model: str = "llama-3.3-70b"
    ):
        """
        Initialize orchestrator.
        
        Args:
            github_client: GitHub API client
            groq_client: Groq API client
            cache_manager: Cache manager for repos and runs
            fast_model: Model for agents 1 and 2
            powerful_model: Model for agent 3
        """
        self.github = github_client
        self.groq = groq_client
        self.cache = cache_manager or CacheManager()
        
        # Initialize agents
        self.agent1 = TriageNurseAgent(groq_client, model=fast_model)
        self.agent2 = ArchaeologistAgent(groq_client, model=fast_model)
        self.agent3 = SeniorDevAgent(groq_client, model=powerful_model)
        
        # Callbacks for UI status updates
        self._status_callback: Optional[Callable[[str], None]] = None
    
    def set_status_callback(self, callback: Callable[[str], None]):
        """Set callback for status updates."""
        self._status_callback = callback
    
    def _update_status(self, message: str):
        """Update status via callback if set."""
        logger.info(message)
        if self._status_callback:
            self._status_callback(message)
    
    def run(
        self,
        repo_url: str,
        beginner_only: bool = True,
        top_issues: int = 3,
        selected_issue_number: Optional[int] = None
    ) -> dict:
        """
        Run the complete analysis pipeline.
        
        Args:
            repo_url: GitHub repository URL
            beginner_only: Whether to filter for beginner-friendly issues
            top_issues: Number of top issues to return
            selected_issue_number: Specific issue to analyze (optional)
            
        Returns:
            Dictionary with all outputs and metadata
        """
        start_time = datetime.now()
        error = None
        
        try:
            # Step 1: Fetch repository info
            self._update_status("📡 Fetching repository information...")
            repo = self.github.get_repo(repo_url)
            
            # Step 2: Fetch issues
            self._update_status("🔍 Fetching issues...")
            issues = self.github.get_issues(repo_url, beginner_only=beginner_only)
            
            if not issues:
                self._update_status("⚠️ No issues found matching criteria")
                return {
                    "success": False,
                    "error": "No issues found. Try disabling 'Beginner-only mode' to see all issues.",
                    "repo": repo
                }
            
            self._update_status(f"Found {len(issues)} issues")
            
            # Step 3: Clone repository
            self._update_status("📦 Cloning repository (this may take a moment)...")
            repo_path = self.github.clone_repo(repo_url)
            
            # Get file tree
            self._update_status("🗂️ Analyzing repository structure...")
            file_tree = self.github.get_file_tree(repo_path)
            
            # Step 4: Run Agent 1 - Triage Nurse
            self._update_status("🏥 Agent 1 (Triage Nurse): Ranking issues...")
            agent1_output = self.agent1.run(repo, issues, top_n=top_issues)
            
            if not agent1_output.ranked_issues:
                return {
                    "success": False,
                    "error": "Could not rank any issues",
                    "repo": repo,
                    "agent1_output": agent1_output
                }
            
            # Determine which issue to analyze
            if selected_issue_number:
                target_issue_number = selected_issue_number
            else:
                target_issue_number = agent1_output.selected_issue_number
            
            # Find the target issue
            target_issue = None
            for issue in issues:
                if issue.number == target_issue_number:
                    target_issue = issue
                    break
            
            if not target_issue:
                target_issue_number = agent1_output.ranked_issues[0].number
                for issue in issues:
                    if issue.number == target_issue_number:
                        target_issue = issue
                        break
            
            # Step 5: Run Agent 2 - Archaeologist
            self._update_status(f"🔭 Agent 2 (Archaeologist): Searching code for issue #{target_issue.number}...")
            agent2_output = self.agent2.run(target_issue, repo_path, file_tree)
            
            # Step 6: Run Agent 3 - Senior Dev
            self._update_status("👨‍💻 Agent 3 (Senior Dev): Generating briefing document...")
            agent3_output = self.agent3.run(repo, target_issue, agent1_output, agent2_output)
            
            self._update_status("✅ Analysis complete!")
            
            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()
            
            # Save run log
            run_log = RunLog(
                timestamp=start_time.isoformat(),
                repo_url=repo_url,
                selected_issue=target_issue_number,
                agent1_output=agent1_output,
                agent2_output=agent2_output,
                agent3_output=agent3_output,
                duration_seconds=duration
            )
            
            self.cache.save_run_log(run_log)
            
            return {
                "success": True,
                "repo": repo,
                "issues": issues,
                "target_issue": target_issue,
                "agent1_output": agent1_output,
                "agent2_output": agent2_output,
                "agent3_output": agent3_output,
                "duration_seconds": duration
            }
        
        except Exception as e:
            logger.exception("Pipeline failed")
            error = str(e)
            self._update_status(f"❌ Error: {error}")
            
            return {
                "success": False,
                "error": error
            }
    
    def run_phase1(
        self,
        repo_url: str,
        beginner_only: bool = True,
        top_issues: int = 3
    ) -> dict:
        """
        Run only Phase 1: Issue ranking.
        
        Returns repo info and ranked issues without code analysis.
        """
        try:
            self._update_status("📡 Fetching repository information...")
            repo = self.github.get_repo(repo_url)
            
            self._update_status("🔍 Fetching issues...")
            issues = self.github.get_issues(repo_url, beginner_only=beginner_only)
            
            if not issues:
                return {
                    "success": False,
                    "error": "No issues found matching criteria",
                    "repo": repo
                }
            
            self._update_status(f"🏥 Ranking {len(issues)} issues...")
            agent1_output = self.agent1.run(repo, issues, top_n=top_issues)
            
            return {
                "success": True,
                "repo": repo,
                "issues": issues,
                "agent1_output": agent1_output
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def run_phase2(
        self,
        repo_url: str,
        issue: GitHubIssue
    ) -> dict:
        """
        Run Phase 2: Code location for a specific issue.
        """
        try:
            self._update_status("📦 Cloning repository...")
            repo_path = self.github.clone_repo(repo_url)
            
            self._update_status("🗂️ Analyzing repository structure...")
            file_tree = self.github.get_file_tree(repo_path)
            
            self._update_status(f"🔭 Searching code for issue #{issue.number}...")
            agent2_output = self.agent2.run(issue, repo_path, file_tree)
            
            return {
                "success": True,
                "agent2_output": agent2_output,
                "repo_path": repo_path
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def run_phase3(
        self,
        repo: GitHubRepo,
        issue: GitHubIssue,
        agent1_output: Agent1Output,
        agent2_output: Agent2Output
    ) -> dict:
        """
        Run Phase 3: Generate briefing document.
        """
        try:
            self._update_status("👨‍💻 Generating contributor briefing...")
            agent3_output = self.agent3.run(repo, issue, agent1_output, agent2_output)
            
            return {
                "success": True,
                "agent3_output": agent3_output
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
