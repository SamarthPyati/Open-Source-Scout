"""
Unit tests for scoring algorithm.
"""
import pytest
from datetime import datetime, timezone, timedelta

from core.scoring import IssueScorer, ScoreResult
from core.schemas import GitHubIssue


@pytest.fixture
def scorer():
    """Create a scorer instance."""
    return IssueScorer()


def create_issue(
    number: int = 1,
    title: str = "Test issue",
    body: str = None,
    labels: list = None,
    comments: int = 0,
    days_old: int = 7
) -> GitHubIssue:
    """Helper to create test issues."""
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=days_old)
    updated = now - timedelta(days=1)
    
    return GitHubIssue(
        number=number,
        title=title,
        body=body,
        url=f"https://api.github.com/repos/test/repo/issues/{number}",
        html_url=f"https://github.com/test/repo/issues/{number}",
        labels=labels or [],
        state="open",
        created_at=created.isoformat(),
        updated_at=updated.isoformat(),
        comments=comments
    )


class TestIssueScoring:
    """Tests for issue scoring algorithm."""
    
    def test_good_first_issue_label_scores_high(self, scorer):
        """Issues with 'good first issue' label should score high on labels."""
        issue = create_issue(labels=["good first issue"])
        result = scorer.score_issue(issue)
        
        assert result.breakdown.labels == 25
        assert result.total >= 40
    
    def test_help_wanted_label_scores_medium(self, scorer):
        """Issues with 'help wanted' label should score 15 on labels."""
        issue = create_issue(labels=["help wanted"])
        result = scorer.score_issue(issue)
        
        assert result.breakdown.labels == 15
    
    def test_no_labels_scores_zero(self, scorer):
        """Issues with no labels should score 0 on labels."""
        issue = create_issue(labels=[])
        result = scorer.score_issue(issue)
        
        assert result.breakdown.labels == 0
    
    def test_clear_description_scores_high_clarity(self, scorer):
        """Issues with clear descriptions should score high on clarity."""
        body = """
        ## Steps to Reproduce
        1. Install the package
        2. Run the following code:
        ```python
        import example
        example.broken_function()
        ```
        
        ## Expected Behavior
        Should return True
        
        ## Actual Behavior
        Returns None and raises an error
        
        ## Environment
        - Python 3.11
        - Package version 1.0.0
        """
        
        issue = create_issue(
            title="Clear bug report with all details",
            body=body
        )
        result = scorer.score_issue(issue)
        
        assert result.breakdown.clarity >= 15
    
    def test_short_description_scores_low_clarity(self, scorer):
        """Issues with short descriptions should score low on clarity."""
        issue = create_issue(
            title="Bug",
            body="Something is broken"
        )
        result = scorer.score_issue(issue)
        
        assert result.breakdown.clarity < 10
    
    def test_recent_activity_scores_high(self, scorer):
        """Recently updated issues should score high on activity."""
        issue = create_issue(days_old=3)
        result = scorer.score_issue(issue)
        
        assert result.breakdown.activity >= 10
    
    def test_no_comments_good_for_beginners(self, scorer):
        """Issues with no comments should score higher (clean slate)."""
        issue = create_issue(comments=0)
        result = scorer.score_issue(issue)
        
        # No comments gives bonus for "clean slate"
        assert result.breakdown.activity >= 3
    
    def test_typo_fix_scores_high_size(self, scorer):
        """Small tasks like typo fixes should score high on size estimate."""
        issue = create_issue(
            title="Fix typo in README",
            body="There's a typo in the README file. It says 'teh' instead of 'the'."
        )
        result = scorer.score_issue(issue)
        
        assert result.breakdown.size_estimate >= 15
    
    def test_large_refactor_scores_low_size(self, scorer):
        """Large refactoring tasks should score low on size estimate."""
        issue = create_issue(
            title="Refactor entire codebase",
            body="We need to refactor and rewrite the entire database layer. This is a major undertaking that affects multiple files and requires migration scripts."
        )
        result = scorer.score_issue(issue)
        
        assert result.breakdown.size_estimate <= 10
    
    def test_breaking_change_has_risk_penalty(self, scorer):
        """Issues with breaking change labels should have risk penalty."""
        issue = create_issue(labels=["breaking change"])
        result = scorer.score_issue(issue)
        
        assert result.breakdown.risk_penalty < 0
    
    def test_security_issue_has_risk_penalty(self, scorer):
        """Security issues should have risk penalty."""
        issue = create_issue(
            title="Fix security vulnerability in authentication",
            body="There's a security issue with password handling"
        )
        result = scorer.score_issue(issue)
        
        assert result.breakdown.risk_penalty < 0
    
    def test_total_score_clamped_to_100(self, scorer):
        """Total score should never exceed 100."""
        issue = create_issue(
            labels=["good first issue"],
            title="Clear and detailed documentation update with steps to reproduce",
            body="A" * 1000,  # Long description
            comments=0,
            days_old=1
        )
        result = scorer.score_issue(issue)
        
        assert result.total <= 100
    
    def test_total_score_clamped_to_zero(self, scorer):
        """Total score should never go below 0."""
        issue = create_issue(
            labels=["breaking change", "security", "complex"],
            title="Major security refactor with breaking changes",
            body="Refactor security, migration, database schema changes"
        )
        result = scorer.score_issue(issue)
        
        assert result.total >= 0
    
    def test_score_result_has_reasons(self, scorer):
        """Score result should include reasons list."""
        issue = create_issue(labels=["good first issue"])
        result = scorer.score_issue(issue)
        
        assert len(result.reasons) > 0
        assert isinstance(result.reasons, list)
    
    def test_ranking_orders_by_score(self, scorer):
        """Ranking should order issues by total score descending."""
        issues = [
            create_issue(number=1, labels=[]),
            create_issue(number=2, labels=["good first issue"]),
            create_issue(number=3, labels=["help wanted"]),
        ]
        
        ranked = scorer.rank_issues(issues, top_n=3)
        
        # Issue 2 should be first (good first issue label)
        assert ranked[0][0].number == 2
        
        # Scores should be in descending order
        scores = [r[1].total for r in ranked]
        assert scores == sorted(scores, reverse=True)
    
    def test_ranking_limits_results(self, scorer):
        """Ranking should limit to top_n results."""
        issues = [create_issue(number=i) for i in range(10)]
        
        ranked = scorer.rank_issues(issues, top_n=3)
        
        assert len(ranked) == 3


class TestScoreBreakdown:
    """Tests for score breakdown correctness."""
    
    def test_breakdown_sums_to_total(self, scorer):
        """Score breakdown components should sum to approximately total."""
        issue = create_issue(
            labels=["help wanted"],
            title="Normal issue with some description",
            body="A normal issue body with some content"
        )
        result = scorer.score_issue(issue)
        
        # Calculate sum of components
        breakdown = result.breakdown
        component_sum = (
            breakdown.labels +
            breakdown.clarity +
            breakdown.activity +
            breakdown.size_estimate +
            breakdown.risk_penalty
        )
        
        # Allow for clamping
        expected_total = max(0, min(100, component_sum))
        assert result.total == expected_total
    
    def test_breakdown_labels_max_25(self, scorer):
        """Labels score should max out at 25."""
        issue = create_issue(labels=["good first issue", "help wanted", "beginner"])
        result = scorer.score_issue(issue)
        
        assert result.breakdown.labels <= 25
    
    def test_breakdown_clarity_max_20(self, scorer):
        """Clarity score should max out at 20."""
        issue = create_issue(
            title="Very clear and detailed title for the issue",
            body="A" * 2000  # Very long body
        )
        result = scorer.score_issue(issue)
        
        assert result.breakdown.clarity <= 20
    
    def test_breakdown_activity_max_15(self, scorer):
        """Activity score should max out at 15."""
        issue = create_issue(days_old=1, comments=0)
        result = scorer.score_issue(issue)
        
        assert result.breakdown.activity <= 15
    
    def test_breakdown_size_max_20(self, scorer):
        """Size estimate score should max out at 20."""
        issue = create_issue(body="typo fix simple quick")
        result = scorer.score_issue(issue)
        
        assert result.breakdown.size_estimate <= 20
    
    def test_breakdown_risk_min_negative_20(self, scorer):
        """Risk penalty should be at most -20."""
        issue = create_issue(
            labels=["breaking change", "security", "complex"],
            body="refactor rewrite security performance migration"
        )
        result = scorer.score_issue(issue)
        
        assert result.breakdown.risk_penalty >= -20
