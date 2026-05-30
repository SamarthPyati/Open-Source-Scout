"""
Deterministic repository health audit.

Scans a cloned repository for technical-debt markers and debug artifacts,
then derives a readiness score (0-100) and a pass/fail gate. No LLM calls are
made, so the audit is fast, reproducible, and free of API cost.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from core.schemas import (
    AuditFinding,
    AuditFileSummary,
    AuditSeverityCounts,
    RepoAuditReport,
)

READINESS_THRESHOLD = 70

MAX_FILES = 4000
MAX_FILE_BYTES = 1_500_000
MAX_LINE_SCAN_LENGTH = 500
MAX_FINDINGS = 400
MAX_TOP_FILES = 10
SNIPPET_LENGTH = 200

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

_SEVERITY_WEIGHTS = {SEVERITY_HIGH: 3.0, SEVERITY_MEDIUM: 1.0, SEVERITY_LOW: 0.4}
_SCORE_SENSITIVITY = 6.0

_HIGH_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bFIXME\b", re.IGNORECASE), "FIXME"),
    (re.compile(r"\bHACK\b", re.IGNORECASE), "HACK"),
    (re.compile(r"\bXXX\b"), "XXX"),
    (re.compile(r"\bBUG\b"), "BUG"),
]

_SKIP_FILE_SUFFIXES = (
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Cargo.lock",
)

_PASSLIB_DEPRECATED = re.compile(r"""deprecated\s*=\s*['"]auto['"]""", re.IGNORECASE)

_MEDIUM_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bTODO\b", re.IGNORECASE), "TODO"),
    (re.compile(r"\bTBD\b", re.IGNORECASE), "TBD"),
    (re.compile(r"\bWIP\b"), "WIP"),
    (re.compile(r"\bDEPRECATED\b", re.IGNORECASE), "DEPRECATED"),
]

_LOW_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"console\.(?:log|debug|trace)\s*\("), "console-log"),
    (re.compile(r"\bdebugger\b\s*;?"), "debugger"),
    (re.compile(r"\bpdb\.set_trace\s*\("), "pdb-set-trace"),
    (re.compile(r"\bbreakpoint\s*\(\s*\)"), "breakpoint"),
    (re.compile(r"\bbinding\.pry\b"), "binding-pry"),
    (re.compile(r"\bvar_dump\s*\("), "var-dump"),
]


def _should_skip_file(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").lower()
    if normalized.startswith("tests/") or "/tests/" in normalized:
        return True
    if normalized.endswith(_SKIP_FILE_SUFFIXES):
        return True
    return False


def _classify_line(line: str) -> Optional[Tuple[str, str, str]]:
    """Return (severity, category, marker) for the highest-severity match, or None."""
    if _PASSLIB_DEPRECATED.search(line):
        return None

    for pattern, marker in _HIGH_PATTERNS:
        if pattern.search(line):
            return SEVERITY_HIGH, marker, marker
    for pattern, marker in _MEDIUM_PATTERNS:
        if pattern.search(line):
            return SEVERITY_MEDIUM, marker, marker
    for pattern, marker in _LOW_PATTERNS:
        if pattern.search(line):
            return SEVERITY_LOW, "debug-artifact", marker
    return None


def _compute_readiness(counts: AuditSeverityCounts, lines_scanned: int) -> int:
    """Derive a 0-100 readiness score from weighted finding density per 1000 lines."""
    weighted = (
        counts.high * _SEVERITY_WEIGHTS[SEVERITY_HIGH]
        + counts.medium * _SEVERITY_WEIGHTS[SEVERITY_MEDIUM]
        + counts.low * _SEVERITY_WEIGHTS[SEVERITY_LOW]
    )
    per_kloc = (weighted / max(lines_scanned, 1)) * 1000
    score = round(100 - per_kloc * _SCORE_SENSITIVITY)
    return max(0, min(100, score))


def _build_summary(report: RepoAuditReport) -> str:
    gate = "PASSED" if report.gate_passed else "FAILED"
    counts = report.severity_counts
    return (
        f"Gate {gate} — readiness {report.readiness_score}/100. "
        f"Scanned {report.files_scanned} files ({report.lines_scanned} lines) and found "
        f"{report.technical_debt} issues "
        f"({counts.high} high, {counts.medium} medium, {counts.low} low)."
    )


def _build_markdown(report: RepoAuditReport) -> str:
    counts = report.severity_counts
    gate = "PASSED" if report.gate_passed else "FAILED"
    lines: List[str] = [
        f"# Repository Health Audit: {report.repo_full_name}",
        "",
        f"- **Readiness score:** {report.readiness_score}/100 (threshold {report.readiness_threshold})",
        f"- **Gate:** {gate}",
        f"- **Technical debt (total findings):** {report.technical_debt}",
        f"- **Files scanned:** {report.files_scanned}",
        f"- **Lines scanned:** {report.lines_scanned}",
        f"- **Scanned at:** {report.scanned_at}",
        "",
        "## Severity breakdown",
        "",
        f"- High: {counts.high}",
        f"- Medium: {counts.medium}",
        f"- Low: {counts.low}",
        "",
    ]

    if report.top_files:
        lines.append("## Files with the most findings")
        lines.append("")
        lines.append("| File | Issues | High | Medium | Low |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for f in report.top_files:
            lines.append(
                f"| {f.file_path} | {f.issue_count} | {f.high} | {f.medium} | {f.low} |"
            )
        lines.append("")

    if report.findings:
        shown = report.findings[:50]
        lines.append("## Sample findings")
        lines.append("")
        lines.append("| Severity | Category | Location | Snippet |")
        lines.append("| --- | --- | --- | --- |")
        for finding in shown:
            snippet = finding.snippet.replace("|", "\\|")
            location = f"{finding.file_path}:{finding.line_number}"
            lines.append(
                f"| {finding.severity} | {finding.category} | {location} | `{snippet}` |"
            )
        if report.findings_truncated or len(report.findings) > len(shown):
            lines.append("")
            lines.append(
                f"_Showing {len(shown)} of {report.technical_debt} findings._"
            )
        lines.append("")

    return "\n".join(lines)


def audit_repository(
    repo_url: str,
    repo_full_name: str,
    repo_path: Path,
    file_tree: List[str],
) -> RepoAuditReport:
    """
    Scan a cloned repository and produce a health audit report.

    Args:
        repo_url: Original repository URL.
        repo_full_name: owner/repo identifier.
        repo_path: Path to the locally cloned repository.
        file_tree: Repo-relative file paths to scan (already filtered of binaries).

    Returns:
        A populated RepoAuditReport.
    """
    repo_path = Path(repo_path)
    counts = AuditSeverityCounts()
    findings: List[AuditFinding] = []
    file_stats: dict[str, dict[str, int]] = {}
    files_scanned = 0
    lines_scanned = 0
    findings_truncated = False

    for rel_path in file_tree[:MAX_FILES]:
        if _should_skip_file(rel_path):
            continue

        full_path = repo_path / rel_path
        try:
            if not full_path.is_file() or full_path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue

        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as handle:
                files_scanned += 1
                for line_number, raw_line in enumerate(handle, 1):
                    lines_scanned += 1
                    line = raw_line[:MAX_LINE_SCAN_LENGTH]
                    classified = _classify_line(line)
                    if classified is None:
                        continue

                    severity, category, marker = classified
                    setattr(counts, severity, getattr(counts, severity) + 1)

                    stats = file_stats.setdefault(
                        rel_path, {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 0, SEVERITY_LOW: 0}
                    )
                    stats[severity] += 1

                    if len(findings) < MAX_FINDINGS:
                        findings.append(
                            AuditFinding(
                                file_path=rel_path,
                                line_number=line_number,
                                severity=severity,
                                category=category,
                                marker=marker,
                                snippet=raw_line.strip()[:SNIPPET_LENGTH],
                            )
                        )
                    else:
                        findings_truncated = True
        except OSError:
            continue

    technical_debt = counts.high + counts.medium + counts.low
    readiness_score = _compute_readiness(counts, lines_scanned)

    top_files = [
        AuditFileSummary(
            file_path=path,
            issue_count=stats[SEVERITY_HIGH] + stats[SEVERITY_MEDIUM] + stats[SEVERITY_LOW],
            high=stats[SEVERITY_HIGH],
            medium=stats[SEVERITY_MEDIUM],
            low=stats[SEVERITY_LOW],
        )
        for path, stats in file_stats.items()
    ]
    top_files.sort(key=lambda f: (f.issue_count, f.high, f.medium), reverse=True)
    top_files = top_files[:MAX_TOP_FILES]

    report = RepoAuditReport(
        repo_url=repo_url,
        repo_full_name=repo_full_name,
        readiness_score=readiness_score,
        gate_passed=readiness_score >= READINESS_THRESHOLD,
        readiness_threshold=READINESS_THRESHOLD,
        technical_debt=technical_debt,
        files_scanned=files_scanned,
        lines_scanned=lines_scanned,
        severity_counts=counts,
        top_files=top_files,
        findings=findings,
        findings_truncated=findings_truncated,
        summary="",
        report_markdown="",
        scanned_at=datetime.now(timezone.utc).isoformat(),
    )
    report.summary = _build_summary(report)
    report.report_markdown = _build_markdown(report)
    return report
