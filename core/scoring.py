"""
Issue Scoring Algorithm - Rule-based scoring for GitHub issues.

Scoring breakdown (0-100 total):
- Labels: 0-25 points (good first issue, help wanted, bug, etc.)
- Clarity: 0-20 points (description length, formatting, reproducibility)
- Activity: 0-15 points (recency, comment activity)
- Size Estimate: 0-20 points (estimated effort based on description)
- Risk Penalty: -20 to 0 points (complexity signals, breaking changes)
"""
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional
from dataclasses import dataclass

from core.schemas import GitHubIssue, ScoreBreakdown


@dataclass
class ScoreResult:
    """Result of scoring an issue."""
    total: int
    breakdown: ScoreBreakdown
    reasons: List[str]


class IssueScorer:
    """Score GitHub issues for beginner-friendliness."""
    
    # Label scoring weights
    POSITIVE_LABELS = {
        "good first issue": 25,
        "good-first-issue": 25,
        "first-timers-only": 25,
        "beginner": 20,
        "easy": 20,
        "starter": 20,
        "help wanted": 15,
        "help-wanted": 15,
        "documentation": 15,
        "docs": 15,
        "bug": 10,
        "enhancement": 8,
        "feature": 8,
        "hacktoberfest": 10,
    }
    
    # Labels that increase risk
    RISK_LABELS = {
        "breaking change": -15,
        "breaking-change": -15,
        "complex": -10,
        "difficult": -10,
        "hard": -10,
        "security": -10,
        "performance": -8,
        "critical": -8,
        "urgent": -5,
        "needs-design": -5,
    }
    
    # Keywords indicating good clarity
    CLARITY_KEYWORDS = [
        "steps to reproduce",
        "expected behavior",
        "actual behavior",
        "environment",
        "version",
        "screenshot",
        "error message",
        "stack trace",
        "example",
        "how to",
    ]
    
    # Keywords indicating complexity/risk
    RISK_KEYWORDS = [
        "refactor",
        "rewrite",
        "breaking",
        "migration",
        "deprecate",
        "security",
        "performance",
        "concurrent",
        "async",
        "thread",
        "database schema",
        "api change",
    ]
    
    def score_issue(self, issue: GitHubIssue) -> ScoreResult:
        """
        Score a single issue.
        
        Args:
            issue: GitHub issue to score
            
        Returns:
            ScoreResult with total, breakdown, and reasons
        """
        reasons = []
        
        # Calculate each component
        labels_score, label_reasons = self._score_labels(issue.labels)
        clarity_score, clarity_reasons = self._score_clarity(issue.title, issue.body)
        activity_score, activity_reasons = self._score_activity(
            issue.created_at, issue.updated_at, issue.comments
        )
        size_score, size_reasons = self._score_size(issue.body)
        risk_penalty, risk_reasons = self._calculate_risk(issue.title, issue.body, issue.labels)
        
        # Combine reasons
        reasons.extend(label_reasons)
        reasons.extend(clarity_reasons)
        reasons.extend(activity_reasons)
        reasons.extend(size_reasons)
        reasons.extend(risk_reasons)
        
        # Calculate total
        total = labels_score + clarity_score + activity_score + size_score + risk_penalty
        total = max(0, min(100, total))  # Clamp to 0-100
        
        breakdown = ScoreBreakdown(
            labels=labels_score,
            clarity=clarity_score,
            activity=activity_score,
            size_estimate=size_score,
            risk_penalty=risk_penalty
        )
        
        return ScoreResult(total=total, breakdown=breakdown, reasons=reasons)
    
    def _score_labels(self, labels: List[str]) -> tuple:
        """Score based on issue labels."""
        score = 0
        reasons = []
        
        labels_lower = [l.lower() for l in labels]
        
        # Check positive labels
        for label, points in self.POSITIVE_LABELS.items():
            if label in labels_lower:
                score = max(score, points)  # Take highest matching label
                if points >= 15:
                    reasons.append(f"Has '{label}' label (+{points} pts)")
        
        # Cap at 25
        score = min(25, score)
        
        if not reasons:
            reasons.append("No beginner-friendly labels found")
        
        return score, reasons
    
    def _score_clarity(self, title: str, body: Optional[str]) -> tuple:
        """Score based on issue clarity and formatting."""
        score = 0
        reasons = []
        
        body = body or ""
        full_text = f"{title} {body}".lower()
        
        # Title clarity (0-5 points)
        if len(title) >= 20:
            score += 3
        if len(title) >= 40:
            score += 2
        
        # Body length (0-5 points)
        if len(body) >= 100:
            score += 2
            if len(body) >= 300:
                score += 2
            if len(body) >= 500:
                score += 1
        
        # Clarity keywords (0-5 points)
        keywords_found = 0
        for keyword in self.CLARITY_KEYWORDS:
            if keyword in full_text:
                keywords_found += 1
        
        if keywords_found >= 1:
            score += 2
            reasons.append(f"Good structure with {keywords_found} clarity indicators")
        if keywords_found >= 3:
            score += 3
        
        # Has code blocks (0-3 points)
        if "```" in body:
            score += 3
            reasons.append("Includes code examples")
        
        # Has links (0-2 points)
        if "http" in body or "[" in body:
            score += 2
        
        score = min(20, score)
        
        if not reasons and score > 10:
            reasons.append(f"Well-documented issue ({len(body)} chars)")
        elif not reasons:
            reasons.append("Could use more documentation")
        
        return score, reasons
    
    def _score_activity(
        self,
        created_at: str,
        updated_at: str,
        comments: int
    ) -> tuple:
        """Score based on issue activity and recency."""
        score = 0
        reasons = []
        
        try:
            # Parse dates
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            
            # Recency score (0-10 points)
            days_since_update = (now - updated).days
            
            if days_since_update <= 7:
                score += 10
                reasons.append("Recently active (updated within 1 week)")
            elif days_since_update <= 30:
                score += 7
                reasons.append("Active within last month")
            elif days_since_update <= 90:
                score += 4
            elif days_since_update <= 180:
                score += 2
            else:
                reasons.append("Issue has been inactive for a while")
            
            # Comment activity (0-5 points)
            if comments == 0:
                score += 3  # No comments = less controversial
                reasons.append("No existing discussion (clean slate)")
            elif comments <= 3:
                score += 2
            elif comments <= 10:
                score += 1
            # Many comments might indicate complexity
            
        except Exception:
            score = 7  # Default middle score
        
        score = min(15, score)
        return score, reasons
    
    def _score_size(self, body: Optional[str]) -> tuple:
        """Estimate issue size/effort from description."""
        score = 10  # Default middle score
        reasons = []
        
        body = (body or "").lower()
        
        # Small task indicators
        small_indicators = [
            "typo", "spelling", "grammar", "rename", "update readme",
            "add comment", "documentation", "fix link", "broken link",
            "update dependency", "bump version", "one line", "simple",
            "quick fix", "minor"
        ]
        
        # Large task indicators
        large_indicators = [
            "refactor", "rewrite", "implement", "new feature",
            "redesign", "architecture", "migration", "database",
            "multiple files", "breaking change", "api"
        ]
        
        small_count = sum(1 for ind in small_indicators if ind in body)
        large_count = sum(1 for ind in large_indicators if ind in body)
        
        if small_count >= 2:
            score += 8
            reasons.append("Appears to be a small, focused task")
        elif small_count == 1:
            score += 5
        
        if large_count >= 2:
            score -= 8
            reasons.append("May require significant effort")
        elif large_count == 1:
            score -= 4
        
        # Adjust based on body length (very long = likely complex)
        if len(body) > 2000:
            score -= 3
        
        score = max(0, min(20, score))
        
        if not reasons:
            reasons.append("Moderate effort estimated")
        
        return score, reasons
    
    def _calculate_risk(
        self,
        title: str,
        body: Optional[str],
        labels: List[str]
    ) -> tuple:
        """Calculate risk penalty."""
        penalty = 0
        reasons = []
        
        body = body or ""
        full_text = f"{title} {body}".lower()
        labels_lower = [l.lower() for l in labels]
        
        # Check risk labels
        for label, points in self.RISK_LABELS.items():
            if label in labels_lower:
                penalty += points
                reasons.append(f"Risk: '{label}' label ({points} pts)")
        
        # Check risk keywords
        risk_count = 0
        for keyword in self.RISK_KEYWORDS:
            if keyword in full_text:
                risk_count += 1
        
        if risk_count >= 3:
            penalty -= 10
            reasons.append(f"Multiple complexity indicators found ({risk_count})")
        elif risk_count >= 1:
            penalty -= 3
        
        # Cap penalty
        penalty = max(-20, min(0, penalty))
        
        if penalty == 0:
            reasons.append("No significant risk factors detected")
        
        return penalty, reasons
    
    def rank_issues(
        self,
        issues: List[GitHubIssue],
        top_n: int = 3
    ) -> List[tuple]:
        """
        Rank issues by score.
        
        Args:
            issues: List of issues to rank
            top_n: Number of top issues to return
            
        Returns:
            List of (issue, score_result) tuples, sorted by score
        """
        scored = []
        
        for issue in issues:
            result = self.score_issue(issue)
            scored.append((issue, result))
        
        # Sort by total score descending
        scored.sort(key=lambda x: x[1].total, reverse=True)
        
        return scored[:top_n]
