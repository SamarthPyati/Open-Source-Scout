"""
Code search utilities - uses ripgrep if available, falls back to Python.
"""
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class SearchResult:
    """A single search result."""
    file_path: str
    line_number: int
    line_content: str
    match_text: str


class CodeSearcher:
    """Search code in repositories using ripgrep or Python fallback."""
    
    def __init__(self, repo_path: Path):
        """
        Initialize code searcher.
        
        Args:
            repo_path: Path to the repository to search
        """
        self.repo_path = Path(repo_path)
        self._has_ripgrep = self._check_ripgrep()
    
    def _check_ripgrep(self) -> bool:
        """Check if ripgrep is available on the system."""
        try:
            subprocess.run(
                ["rg", "--version"],
                capture_output=True,
                check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    @property
    def has_ripgrep(self) -> bool:
        """Check if ripgrep is available."""
        return self._has_ripgrep
    
    def search(
        self,
        query: str,
        file_patterns: Optional[List[str]] = None,
        max_results: int = 50,
        context_lines: int = 3,
        case_sensitive: bool = False
    ) -> List[SearchResult]:
        """
        Search for a query in the repository.
        
        Args:
            query: Search query (regex supported)
            file_patterns: File patterns to include (e.g., ["*.py", "*.js"])
            max_results: Maximum number of results
            context_lines: Number of context lines around matches
            case_sensitive: Whether search is case sensitive
            
        Returns:
            List of SearchResult objects
        """
        if self._has_ripgrep:
            return self._search_ripgrep(
                query, file_patterns, max_results, context_lines, case_sensitive
            )
        else:
            return self._search_python(
                query, file_patterns, max_results, case_sensitive
            )
    
    def _search_ripgrep(
        self,
        query: str,
        file_patterns: Optional[List[str]],
        max_results: int,
        context_lines: int,
        case_sensitive: bool
    ) -> List[SearchResult]:
        """Search using ripgrep."""
        cmd = ["rg", "--json", "-n"]
        
        if not case_sensitive:
            cmd.append("-i")
        
        cmd.extend(["-C", str(context_lines)])
        cmd.extend(["-m", str(max_results)])
        
        # Add file patterns
        if file_patterns:
            for pattern in file_patterns:
                cmd.extend(["-g", pattern])
        
        # Exclude common non-code directories
        for exclude in [".git", "node_modules", "__pycache__", "dist", "build", ".venv"]:
            cmd.extend(["--glob", f"!{exclude}"])
        
        cmd.append(query)
        cmd.append(str(self.repo_path))
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            import json
            results = []
            
            for line in result.stdout.split("\n"):
                if not line.strip():
                    continue
                    
                try:
                    data = json.loads(line)
                    if data.get("type") == "match":
                        match_data = data.get("data", {})
                        path = match_data.get("path", {}).get("text", "")
                        line_num = match_data.get("line_number", 0)
                        lines = match_data.get("lines", {}).get("text", "")
                        
                        # Get the relative path
                        try:
                            rel_path = Path(path).relative_to(self.repo_path)
                            path = str(rel_path).replace("\\", "/")
                        except ValueError:
                            pass
                        
                        results.append(SearchResult(
                            file_path=path,
                            line_number=line_num,
                            line_content=lines.strip(),
                            match_text=query
                        ))
                except json.JSONDecodeError:
                    continue
            
            return results[:max_results]
        
        except subprocess.TimeoutExpired:
            return []
        except Exception:
            # Fall back to Python search
            return self._search_python(query, file_patterns, max_results, case_sensitive)
    
    def _search_python(
        self,
        query: str,
        file_patterns: Optional[List[str]],
        max_results: int,
        case_sensitive: bool
    ) -> List[SearchResult]:
        """Pure Python fallback search."""
        results = []
        
        # Compile regex
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query, flags)
        except re.error:
            # If query is not valid regex, escape it
            pattern = re.compile(re.escape(query), flags)
        
        # Get all files
        files_to_search = []
        
        ignore_dirs = {".git", "node_modules", "__pycache__", "dist", "build", ".venv", "venv"}
        
        for root, dirs, files in os.walk(self.repo_path):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            
            for filename in files:
                filepath = Path(root) / filename
                
                # Check file patterns
                if file_patterns:
                    if not any(filepath.match(p) for p in file_patterns):
                        continue
                
                files_to_search.append(filepath)
        
        # Search files
        for filepath in files_to_search:
            if len(results) >= max_results:
                break
            
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, 1):
                        if pattern.search(line):
                            rel_path = filepath.relative_to(self.repo_path)
                            results.append(SearchResult(
                                file_path=str(rel_path).replace("\\", "/"),
                                line_number=line_num,
                                line_content=line.strip(),
                                match_text=query
                            ))
                            
                            if len(results) >= max_results:
                                break
            except Exception:
                continue
        
        return results
    
    def search_multiple(
        self,
        queries: List[str],
        file_patterns: Optional[List[str]] = None,
        max_results_per_query: int = 20
    ) -> dict:
        """
        Search for multiple queries.
        
        Args:
            queries: List of search queries
            file_patterns: File patterns to include
            max_results_per_query: Max results per query
            
        Returns:
            Dictionary mapping query to results
        """
        results = {}
        for query in queries:
            results[query] = self.search(
                query,
                file_patterns=file_patterns,
                max_results=max_results_per_query
            )
        return results
    
    def get_file_content(
        self,
        file_path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
        max_lines: int = 200
    ) -> str:
        """
        Get content of a file.
        
        Args:
            file_path: Relative path to file
            start_line: Starting line (1-indexed)
            end_line: Ending line (inclusive)
            max_lines: Maximum lines to return
            
        Returns:
            File content as string
        """
        full_path = self.repo_path / file_path
        
        if not full_path.exists():
            return ""
        
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return ""
        
        # Adjust indices
        start_idx = max(0, start_line - 1)
        end_idx = end_line if end_line else len(lines)
        end_idx = min(end_idx, start_idx + max_lines)
        
        return "".join(lines[start_idx:end_idx])
    
    def extract_symbols(self, file_path: str) -> List[str]:
        """
        Extract function and class names from a file.
        
        Args:
            file_path: Relative path to file
            
        Returns:
            List of symbol names (functions, classes)
        """
        full_path = self.repo_path / file_path
        
        if not full_path.exists():
            return []
        
        symbols = []
        
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return []
        
        # Python patterns
        if file_path.endswith(".py"):
            # Functions
            for match in re.finditer(r"def\s+(\w+)\s*\(", content):
                symbols.append(match.group(1))
            # Classes
            for match in re.finditer(r"class\s+(\w+)\s*[:\(]", content):
                symbols.append(match.group(1))
        
        # JavaScript/TypeScript patterns
        elif file_path.endswith((".js", ".ts", ".jsx", ".tsx")):
            # Functions
            for match in re.finditer(r"(?:function|const|let|var)\s+(\w+)\s*[\(=]", content):
                symbols.append(match.group(1))
            # Classes
            for match in re.finditer(r"class\s+(\w+)\s*[{\(]", content):
                symbols.append(match.group(1))
        
        # Java/C# patterns
        elif file_path.endswith((".java", ".cs")):
            # Methods and classes
            for match in re.finditer(r"(?:public|private|protected)?\s*(?:static)?\s*(?:class|interface|void|int|String|bool)\s+(\w+)\s*[\({]", content):
                symbols.append(match.group(1))
        
        # Go patterns
        elif file_path.endswith(".go"):
            for match in re.finditer(r"func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", content):
                symbols.append(match.group(1))
            for match in re.finditer(r"type\s+(\w+)\s+(?:struct|interface)", content):
                symbols.append(match.group(1))
        
        # Rust patterns
        elif file_path.endswith(".rs"):
            for match in re.finditer(r"fn\s+(\w+)\s*[<\(]", content):
                symbols.append(match.group(1))
            for match in re.finditer(r"(?:struct|enum|trait|impl)\s+(\w+)\s*[<{]", content):
                symbols.append(match.group(1))
        
        return list(set(symbols))
