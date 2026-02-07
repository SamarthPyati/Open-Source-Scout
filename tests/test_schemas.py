"""
Unit tests for Pydantic schemas.
"""
import pytest
from pydantic import ValidationError

from core.schemas import (
    ScoreBreakdown, RankedIssue, RepoInfo, Agent1Output,
    CodeHit, Agent2Output, PRDraft, Agent3Output,
    GitHubIssue, GitHubRepo
)


class TestScoreBreakdown:
    """Tests for ScoreBreakdown schema."""
    
    def test_valid_score_breakdown(self):
        """Valid score breakdown should parse correctly."""
        breakdown = ScoreBreakdown(
            labels=20,
            clarity=15,
            activity=10,
            size_estimate=15,
            risk_penalty=-5
        )
        
        assert breakdown.labels == 20
        assert breakdown.risk_penalty == -5
    
    def test_labels_max_validation(self):
        """Labels score should not exceed 25."""
        with pytest.raises(ValidationError):
            ScoreBreakdown(
                labels=30,  # Too high
                clarity=15,
                activity=10,
                size_estimate=15,
                risk_penalty=0
            )
    
    def test_risk_penalty_negative_validation(self):
        """Risk penalty should be between -20 and 0."""
        with pytest.raises(ValidationError):
            ScoreBreakdown(
                labels=20,
                clarity=15,
                activity=10,
                size_estimate=15,
                risk_penalty=5  # Should be negative or zero
            )


class TestRankedIssue:
    """Tests for RankedIssue schema."""
    
    def test_valid_ranked_issue(self):
        """Valid ranked issue should parse correctly."""
        issue = RankedIssue(
            number=123,
            title="Fix bug in login",
            url="https://github.com/owner/repo/issues/123",
            labels=["bug", "good first issue"],
            score_total=75,
            score_breakdown=ScoreBreakdown(
                labels=25,
                clarity=18,
                activity=12,
                size_estimate=15,
                risk_penalty=-5
            ),
            why=["Clear description", "Good first issue label"]
        )
        
        assert issue.number == 123
        assert issue.score_total == 75
        assert len(issue.why) == 2
    
    def test_score_total_range(self):
        """Score total should be between 0 and 100."""
        with pytest.raises(ValidationError):
            RankedIssue(
                number=1,
                title="Test",
                url="https://example.com",
                labels=[],
                score_total=150,  # Too high
                score_breakdown=ScoreBreakdown(
                    labels=0, clarity=0, activity=0, 
                    size_estimate=0, risk_penalty=0
                ),
                why=[]
            )


class TestAgent1Output:
    """Tests for Agent1Output schema."""
    
    def test_valid_agent1_output(self):
        """Valid Agent1 output should parse correctly."""
        output = Agent1Output(
            repo=RepoInfo(
                url="https://github.com/owner/repo",
                default_branch="main",
                description="A test repo",
                languages=["Python", "JavaScript"]
            ),
            ranked_issues=[
                RankedIssue(
                    number=1,
                    title="Issue 1",
                    url="https://github.com/owner/repo/issues/1",
                    labels=["bug"],
                    score_total=80,
                    score_breakdown=ScoreBreakdown(
                        labels=20, clarity=15, activity=15,
                        size_estimate=15, risk_penalty=-5
                    ),
                    why=["Good match"]
                )
            ],
            selected_issue_number=1
        )
        
        assert output.selected_issue_number == 1
        assert len(output.ranked_issues) == 1


class TestAgent2Output:
    """Tests for Agent2Output schema."""
    
    def test_valid_agent2_output(self):
        """Valid Agent2 output should parse correctly."""
        output = Agent2Output(
            issue_number=42,
            keywords=["login", "auth", "user"],
            search_strategy=["search for login function", "find auth module"],
            hits=[
                CodeHit(
                    path="src/auth/login.py",
                    symbols=["login_user", "validate_password"],
                    snippet="def login_user(username, password):\n    ...",
                    why_relevant="Contains login function"
                )
            ],
            call_trace_hint=["login_user", "validate_password", "check_db"],
            confidence="High",
            next_files_to_check=["src/auth/utils.py"]
        )
        
        assert output.issue_number == 42
        assert output.confidence == "High"
        assert len(output.hits) == 1


class TestAgent3Output:
    """Tests for Agent3Output schema."""
    
    def test_valid_agent3_output(self):
        """Valid Agent3 output should parse correctly."""
        output = Agent3Output(
            briefing_markdown="# Contributor Briefing\n\nThis is the briefing...",
            pr_draft=PRDraft(
                branch_name="fix/42-login-bug",
                commit_message="fix: resolve login validation issue",
                pr_title="Fix login validation bug",
                pr_body="## Description\nFixes #42"
            ),
            test_commands=["pytest tests/", "npm test"],
            risk_notes=["May affect authentication flow"]
        )
        
        assert "Contributor Briefing" in output.briefing_markdown
        assert output.pr_draft.branch_name == "fix/42-login-bug"


class TestGitHubIssue:
    """Tests for GitHubIssue schema."""
    
    def test_valid_github_issue(self):
        """Valid GitHub issue should parse correctly."""
        issue = GitHubIssue(
            number=100,
            title="Add feature X",
            body="Please add feature X because...",
            url="https://api.github.com/repos/owner/repo/issues/100",
            html_url="https://github.com/owner/repo/issues/100",
            labels=["enhancement"],
            state="open",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-02T00:00:00Z",
            comments=5
        )
        
        assert issue.number == 100
        assert issue.comments == 5
    
    def test_optional_body(self):
        """Body field should be optional."""
        issue = GitHubIssue(
            number=1,
            title="Test",
            url="https://api.github.com/repos/owner/repo/issues/1",
            html_url="https://github.com/owner/repo/issues/1",
            state="open",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z"
        )
        
        assert issue.body is None


class TestGitHubRepo:
    """Tests for GitHubRepo schema."""
    
    def test_valid_github_repo(self):
        """Valid GitHub repo should parse correctly."""
        repo = GitHubRepo(
            full_name="owner/repo",
            description="A cool project",
            default_branch="main",
            html_url="https://github.com/owner/repo",
            clone_url="https://github.com/owner/repo.git",
            language="Python",
            languages={"Python": 10000, "JavaScript": 5000},
            stargazers_count=100,
            open_issues_count=10
        )
        
        assert repo.full_name == "owner/repo"
        assert repo.stargazers_count == 100
    
    def test_default_values(self):
        """Default values should be applied correctly."""
        repo = GitHubRepo(
            full_name="owner/repo",
            html_url="https://github.com/owner/repo",
            clone_url="https://github.com/owner/repo.git"
        )
        
        assert repo.default_branch == "main"
        assert repo.stargazers_count == 0
        assert repo.languages == {}
