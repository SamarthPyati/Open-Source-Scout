"""
Cache management utilities for repositories and run logs.
"""
import os
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.schemas import RunLog


class CacheManager:
    """Manages caching for repositories and run logs."""
    
    def __init__(self, base_dir: str = ".cache"):
        """
        Initialize cache manager.
        
        Args:
            base_dir: Base directory for all caches
        """
        self.base_dir = Path(base_dir)
        self.repos_dir = self.base_dir / "repos"
        self.runs_dir = self.base_dir / "runs"
        
        # Create directories
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
    
    def get_repo_cache_path(self, repo_url: str) -> Path:
        """
        Get cache path for a repository.
        
        Args:
            repo_url: GitHub repository URL
            
        Returns:
            Path to cached repository directory
        """
        # Create hash from URL
        url_hash = hashlib.md5(repo_url.encode()).hexdigest()[:12]
        return self.repos_dir / url_hash
    
    def is_repo_cached(self, repo_url: str) -> bool:
        """Check if repository is already cached."""
        cache_path = self.get_repo_cache_path(repo_url)
        return cache_path.exists() and any(cache_path.iterdir())
    
    def save_run_log(self, run_log: RunLog) -> Path:
        """
        Save run log to file.
        
        Args:
            run_log: RunLog object to save
            
        Returns:
            Path to saved log file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.runs_dir / f"{timestamp}.json"
        
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(run_log.model_dump_json(indent=2))
        
        return log_file
    
    def get_recent_runs(self, limit: int = 10) -> list:
        """
        Get recent run logs.
        
        Args:
            limit: Maximum number of runs to return
            
        Returns:
            List of RunLog objects
        """
        logs = []
        log_files = sorted(self.runs_dir.glob("*.json"), reverse=True)
        
        for log_file in log_files[:limit]:
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    logs.append(RunLog.model_validate(data))
            except Exception:
                continue
        
        return logs
    
    def clear_old_repos(self, max_age_days: int = 7):
        """
        Clear repositories older than specified days.
        
        Args:
            max_age_days: Maximum age in days before deletion
        """
        import shutil
        from datetime import timedelta
        
        now = datetime.now()
        cutoff = now - timedelta(days=max_age_days)
        
        for repo_dir in self.repos_dir.iterdir():
            if repo_dir.is_dir():
                mtime = datetime.fromtimestamp(repo_dir.stat().st_mtime)
                if mtime < cutoff:
                    shutil.rmtree(repo_dir, ignore_errors=True)
    
    def get_cache_size(self) -> dict:
        """Get total cache size information."""
        def get_dir_size(path: Path) -> int:
            total = 0
            for item in path.rglob("*"):
                if item.is_file():
                    total += item.stat().st_size
            return total
        
        repos_size = get_dir_size(self.repos_dir) if self.repos_dir.exists() else 0
        runs_size = get_dir_size(self.runs_dir) if self.runs_dir.exists() else 0
        
        return {
            "repos_mb": round(repos_size / (1024 * 1024), 2),
            "runs_mb": round(runs_size / (1024 * 1024), 2),
            "total_mb": round((repos_size + runs_size) / (1024 * 1024), 2)
        }
