"""Tests for the deterministic repository health audit."""
from pathlib import Path

from core.audit.repo_auditor import READINESS_THRESHOLD, audit_repository


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_clean_repo_passes_gate(tmp_path: Path):
    _write(tmp_path, "main.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path, "util.js", "export const ok = () => 42\n")
    file_tree = ["main.py", "util.js"]

    report = audit_repository(
        repo_url="https://github.com/o/clean",
        repo_full_name="o/clean",
        repo_path=tmp_path,
        file_tree=file_tree,
    )

    assert report.technical_debt == 0
    assert report.readiness_score == 100
    assert report.gate_passed is True
    assert report.files_scanned == 2


def test_markers_are_classified_by_severity(tmp_path: Path):
    _write(
        tmp_path,
        "app.py",
        "# TODO: refactor\n"
        "x = 1  # FIXME broken\n"
        "console.log('debug')\n",
    )
    file_tree = ["app.py"]

    report = audit_repository(
        repo_url="https://github.com/o/debt",
        repo_full_name="o/debt",
        repo_path=tmp_path,
        file_tree=file_tree,
    )

    assert report.severity_counts.high == 1
    assert report.severity_counts.medium == 1
    assert report.severity_counts.low == 1
    assert report.technical_debt == 3
    assert report.top_files[0].file_path == "app.py"
    assert report.top_files[0].issue_count == 3


def test_highest_severity_wins_per_line(tmp_path: Path):
    _write(tmp_path, "mix.py", "y = 2  # TODO and FIXME on one line\n")

    report = audit_repository(
        repo_url="https://github.com/o/mix",
        repo_full_name="o/mix",
        repo_path=tmp_path,
        file_tree=["mix.py"],
    )

    assert report.severity_counts.high == 1
    assert report.severity_counts.medium == 0
    assert report.technical_debt == 1


def test_high_debt_density_fails_gate_and_builds_report(tmp_path: Path):
    body = "".join(f"# FIXME issue {i}\n" for i in range(40))
    _write(tmp_path, "legacy.py", body)

    report = audit_repository(
        repo_url="https://github.com/o/legacy",
        repo_full_name="o/legacy",
        repo_path=tmp_path,
        file_tree=["legacy.py"],
    )

    assert report.severity_counts.high == 40
    assert report.readiness_score < READINESS_THRESHOLD
    assert report.gate_passed is False
    assert "Repository Health Audit" in report.report_markdown
    assert report.summary


def test_missing_files_are_skipped(tmp_path: Path):
    _write(tmp_path, "present.py", "# TODO only here\n")
    file_tree = ["present.py", "does_not_exist.py"]

    report = audit_repository(
        repo_url="https://github.com/o/partial",
        repo_full_name="o/partial",
        repo_path=tmp_path,
        file_tree=file_tree,
    )

    assert report.files_scanned == 1
    assert report.severity_counts.medium == 1


def test_skips_tests_and_lockfiles(tmp_path: Path):
    _write(tmp_path, "tests/test_x.py", "# FIXME in tests\n")
    _write(tmp_path, "frontend/package-lock.json", '"deprecated": "old package"\n')
    _write(tmp_path, "src/app.py", "# TODO real\n")

    report = audit_repository(
        repo_url="https://github.com/o/filter",
        repo_full_name="o/filter",
        repo_path=tmp_path,
        file_tree=["tests/test_x.py", "frontend/package-lock.json", "src/app.py"],
    )

    assert report.files_scanned == 1
    assert report.technical_debt == 1
    assert report.severity_counts.medium == 1


def test_passlib_deprecated_auto_not_flagged(tmp_path: Path):
    _write(
        tmp_path,
        "app/auth_service.py",
        'pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")\n',
    )

    report = audit_repository(
        repo_url="https://github.com/o/auth",
        repo_full_name="o/auth",
        repo_path=tmp_path,
        file_tree=["app/auth_service.py"],
    )

    assert report.technical_debt == 0


def test_pattern_definition_lines_not_flagged(tmp_path: Path):
    _write(
        tmp_path,
        "scanner.py",
        '(re.compile(r"\\bFIXME\\b", re.IGNORECASE), "FIXME"),\n'
        "# TODO: real debt here\n",
    )

    report = audit_repository(
        repo_url="https://github.com/o/scanner",
        repo_full_name="o/scanner",
        repo_path=tmp_path,
        file_tree=["scanner.py"],
    )

    assert report.technical_debt == 1
    assert report.severity_counts.medium == 1
    assert report.findings[0].category == "TODO"
