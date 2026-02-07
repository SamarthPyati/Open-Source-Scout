"""
Pydantic schemas for agent outputs and data validation.
These schemas ensure strict JSON output from LLMs.
"""
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


# ==================== Agent 1: Triage Nurse ====================

class ScoreBreakdown(BaseModel):
    """Breakdown of score components for an issue."""
    labels: int = Field(ge=0, le=25, description="Score from labels (0-25)")
    clarity: int = Field(ge=0, le=20, description="Score from clarity (0-20)")
    activity: int = Field(ge=0, le=15, description="Score from activity (0-15)")
    size_estimate: int = Field(ge=0, le=20, description="Score from size estimate (0-20)")
    risk_penalty: int = Field(ge=-20, le=0, description="Risk penalty (-20 to 0)")


class RankedIssue(BaseModel):
    """A ranked GitHub issue with score breakdown."""
    number: int = Field(description="Issue number")
    title: str = Field(description="Issue title")
    url: str = Field(description="Issue URL")
    labels: List[str] = Field(default_factory=list, description="Issue labels")
    score_total: int = Field(ge=0, le=100, description="Total score (0-100)")
    score_breakdown: ScoreBreakdown = Field(description="Score breakdown by category")
    why: List[str] = Field(description="Bullet points explaining why this issue was selected")


class RepoInfo(BaseModel):
    """Basic repository information."""
    url: str = Field(description="Repository URL")
    default_branch: str = Field(description="Default branch name")
    description: Optional[str] = Field(default=None, description="Repository description")
    languages: Optional[List[str]] = Field(default=None, description="Primary languages")


class Agent1Output(BaseModel):
    """Output from Agent 1: Triage Nurse (Issue Ranking)"""
    repo: RepoInfo = Field(description="Repository information")
    ranked_issues: List[RankedIssue] = Field(description="Top ranked issues")
    selected_issue_number: int = Field(description="The selected issue number for next step")


# ==================== Agent 2: Archaeologist ====================

class CodeHit(BaseModel):
    """A code search hit with relevance information."""
    path: str = Field(description="File path relative to repo root")
    symbols: List[str] = Field(default_factory=list, description="Function/class names found")
    snippet: str = Field(description="Code snippet (max 200 lines)")
    why_relevant: str = Field(description="Explanation of why this code is relevant")


class Agent2Output(BaseModel):
    """Output from Agent 2: Archaeologist (Code Locator)"""
    issue_number: int = Field(description="The issue being analyzed")
    keywords: List[str] = Field(description="Keywords extracted from issue")
    search_strategy: List[str] = Field(description="Search strategies used")
    hits: List[CodeHit] = Field(description="Code locations found")
    call_trace_hint: List[str] = Field(default_factory=list, description="Suggested call trace")
    confidence: str = Field(description="Confidence level: High, Medium, or Low")
    next_files_to_check: List[str] = Field(default_factory=list, description="Additional files to review")


# ==================== Agent 3: Senior Dev ====================

class PRDraft(BaseModel):
    """Draft pull request content."""
    branch_name: str = Field(description="Suggested branch name")
    commit_message: str = Field(description="Suggested commit message")
    pr_title: str = Field(description="Pull request title")
    pr_body: str = Field(description="Pull request description/body")


class Agent3Output(BaseModel):
    """Output from Agent 3: Senior Dev (Fix Plan Generator)"""
    briefing_markdown: str = Field(description="Full contributor briefing document in Markdown")
    pr_draft: PRDraft = Field(description="Draft PR content")
    test_commands: List[str] = Field(default_factory=list, description="Commands to run tests")
    risk_notes: List[str] = Field(default_factory=list, description="Potential risks to watch for")


# ==================== GitHub API Models ====================

class GitHubIssue(BaseModel):
    """Representation of a GitHub issue."""
    number: int
    title: str
    body: Optional[str] = None
    url: str
    html_url: str
    labels: List[str] = Field(default_factory=list)
    state: str = "open"
    created_at: str
    updated_at: str
    comments: int = 0
    user: Optional[str] = None


class GitHubRepo(BaseModel):
    """Representation of a GitHub repository."""
    full_name: str
    description: Optional[str] = None
    default_branch: str = "main"
    html_url: str
    clone_url: str
    language: Optional[str] = None
    languages: Dict[str, int] = Field(default_factory=dict)
    stargazers_count: int = 0
    open_issues_count: int = 0


# ==================== Run Log Model ====================

class RunLog(BaseModel):
    """Log entry for a single run."""
    timestamp: str
    repo_url: str
    selected_issue: int
    agent1_output: Optional[Agent1Output] = None
    agent2_output: Optional[Agent2Output] = None
    agent3_output: Optional[Agent3Output] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None
