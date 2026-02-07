"""
GitHub API Client - Fetches issues, repo metadata, and clones repositories.
"""
import os
import re
import hashlib
from typing import List, Optional, Tuple
from pathlib import Path
import requests
from git import Repo as GitRepo
from git.exc import GitCommandError

from core.schemas import GitHubIssue, GitHubRepo


class GitHubClient:
    """Client for interacting with GitHub API and cloning repos."""
    
    BASE_URL = "https://api.github.com"
    
    def __init__(self, token: Optional[str] = None, cache_dir: str = ".cache/repos"):
        """
        Initialize GitHub client.
        
        Args:
            token: GitHub personal access token (optional but recommended)
            cache_dir: Directory to cache cloned repositories
        """
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.session = requests.Session()
        if self.token:
            self.session.headers["Authorization"] = f"token {self.token}"
        self.session.headers["Accept"] = "application/vnd.github.v3+json"
        self.session.headers["User-Agent"] = "Open-Source-Scout/1.0"
    
    @property
    def has_token(self) -> bool:
        """Check if a GitHub token is configured."""
        return bool(self.token)
    
    @property
    def rate_limit_info(self) -> dict:
        """Get current rate limit status."""
        resp = self.session.get(f"{self.BASE_URL}/rate_limit")
        if resp.status_code == 200:
            data = resp.json()
            return {
                "remaining": data["resources"]["core"]["remaining"],
                "limit": data["resources"]["core"]["limit"],
                "reset_at": data["resources"]["core"]["reset"]
            }
        return {"remaining": 0, "limit": 60, "reset_at": 0}
    
    def parse_repo_url(self, url: str) -> Tuple[str, str]:
        """
        Parse owner and repo name from GitHub URL.
        
        Args:
            url: GitHub repository URL
            
        Returns:
            Tuple of (owner, repo_name)
        """
        # Clean the URL - remove trailing slashes and whitespace
        url = url.strip().rstrip('/')
        
        # Handle various URL formats
        patterns = [
            r"github\.com[/:]([^/]+)/([^/?\s]+)",  # https://github.com/owner/repo or git@github.com:owner/repo
            r"^([^/\s]+)/([^/\s]+)$"  # owner/repo format
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                owner, repo = match.groups()
                # Remove .git suffix if present
                if repo.endswith('.git'):
                    repo = repo[:-4]
                return owner, repo
        
        raise ValueError(f"Invalid GitHub URL: {url}")
    
    def get_repo(self, url: str) -> GitHubRepo:
        """
        Fetch repository metadata.
        
        Args:
            url: GitHub repository URL
            
        Returns:
            GitHubRepo object with repository metadata
        """
        owner, repo = self.parse_repo_url(url)
        
        # Get basic repo info
        resp = self.session.get(f"{self.BASE_URL}/repos/{owner}/{repo}")
        resp.raise_for_status()
        data = resp.json()
        
        # Get languages
        lang_resp = self.session.get(f"{self.BASE_URL}/repos/{owner}/{repo}/languages")
        languages = lang_resp.json() if lang_resp.status_code == 200 else {}
        
        return GitHubRepo(
            full_name=data["full_name"],
            description=data.get("description"),
            default_branch=data.get("default_branch", "main"),
            html_url=data["html_url"],
            clone_url=data["clone_url"],
            language=data.get("language"),
            languages=languages,
            stargazers_count=data.get("stargazers_count", 0),
            open_issues_count=data.get("open_issues_count", 0)
        )
    
    def get_issues(
        self, 
        url: str, 
        beginner_only: bool = True,
        max_issues: int = 30
    ) -> List[GitHubIssue]:
        """
        Fetch open issues from repository.
        
        Args:
            url: GitHub repository URL
            beginner_only: If True, filter for beginner-friendly labels
            max_issues: Maximum number of issues to fetch
            
        Returns:
            List of GitHubIssue objects
        """
        owner, repo = self.parse_repo_url(url)
        
        # Labels to look for (GitHub API supports comma-separated for OR)
        beginner_labels = [
            "good first issue",
            "good-first-issue", 
            "help wanted",
            "help-wanted",
            "beginner",
            "easy",
            "starter",
            "first-timers-only"
        ]
        
        all_issues = []
        
        if beginner_only:
            # Fetch issues for each beginner label
            for label in beginner_labels:
                if len(all_issues) >= max_issues:
                    break
                    
                params = {
                    "state": "open",
                    "labels": label,
                    "per_page": min(10, max_issues - len(all_issues)),
                    "sort": "updated",
                    "direction": "desc"
                }
                
                resp = self.session.get(
                    f"{self.BASE_URL}/repos/{owner}/{repo}/issues",
                    params=params
                )
                
                if resp.status_code == 200:
                    for item in resp.json():
                        # Skip pull requests (they appear in issues endpoint)
                        if "pull_request" in item:
                            continue
                        
                        issue = self._parse_issue(item)
                        # Avoid duplicates
                        if not any(i.number == issue.number for i in all_issues):
                            all_issues.append(issue)
        else:
            # Fetch all open issues
            params = {
                "state": "open",
                "per_page": max_issues,
                "sort": "updated",
                "direction": "desc"
            }
            
            resp = self.session.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/issues",
                params=params
            )
            resp.raise_for_status()
            
            for item in resp.json():
                if "pull_request" not in item:
                    all_issues.append(self._parse_issue(item))
        
        return all_issues[:max_issues]
    
    def _parse_issue(self, data: dict) -> GitHubIssue:
        """Parse GitHub API issue response into GitHubIssue model."""
        return GitHubIssue(
            number=data["number"],
            title=data["title"],
            body=data.get("body"),
            url=data["url"],
            html_url=data["html_url"],
            labels=[label["name"] for label in data.get("labels", [])],
            state=data["state"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            comments=data.get("comments", 0),
            user=data.get("user", {}).get("login")
        )
    
    def clone_repo(self, url: str, force_fresh: bool = False) -> Path:
        """
        Clone repository to local cache.
        
        Args:
            url: GitHub repository URL
            force_fresh: If True, delete existing clone and re-clone
            
        Returns:
            Path to cloned repository
        """
        owner, repo = self.parse_repo_url(url)
        
        # Create unique hash for the repo
        repo_hash = hashlib.md5(f"{owner}/{repo}".encode()).hexdigest()[:12]
        repo_dir = self.cache_dir / f"{owner}_{repo}_{repo_hash}"
        
        if repo_dir.exists():
            if force_fresh:
                import shutil
                shutil.rmtree(repo_dir)
            else:
                # Pull latest changes
                try:
                    git_repo = GitRepo(repo_dir)
                    git_repo.remotes.origin.pull()
                    return repo_dir
                except GitCommandError:
                    # If pull fails, do a fresh clone
                    import shutil
                    shutil.rmtree(repo_dir)
        
        # Clone the repository
        clone_url = f"https://github.com/{owner}/{repo}.git"
        try:
            GitRepo.clone_from(
                clone_url,
                repo_dir,
                depth=1,  # Shallow clone for speed
                single_branch=True
            )
        except GitCommandError as e:
            raise RuntimeError(f"Failed to clone repository: {e}")
        
        return repo_dir
    
    def get_file_tree(self, repo_path: Path, max_depth: int = 5) -> List[str]:
        """
        Get list of files in repository (excluding common non-code directories).
        
        Args:
            repo_path: Path to cloned repository
            max_depth: Maximum directory depth to search
            
        Returns:
            List of file paths relative to repo root
        """
        ignore_dirs = {
            ".git", "node_modules", "__pycache__", ".cache",
            "dist", "build", ".next", "vendor", ".venv", "venv",
            "env", ".env", "coverage", ".nyc_output"
        }
        
        ignore_extensions = {
            ".min.js", ".min.css", ".map", ".lock",
            ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
            ".woff", ".woff2", ".ttf", ".eot"
        }
        
        files = []
        
        def walk_dir(path: Path, depth: int = 0):
            if depth > max_depth:
                return
                
            try:
                for item in path.iterdir():
                    if item.name in ignore_dirs:
                        continue
                    
                    if item.is_file():
                        # Skip ignored extensions
                        if any(item.name.endswith(ext) for ext in ignore_extensions):
                            continue
                        
                        rel_path = item.relative_to(repo_path)
                        files.append(str(rel_path).replace("\\", "/"))
                    
                    elif item.is_dir():
                        walk_dir(item, depth + 1)
            except PermissionError:
                pass
        
        walk_dir(repo_path)
        return files
