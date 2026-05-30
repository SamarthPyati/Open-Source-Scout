"""
FastAPI backend for Open Source Scout.

Exposes REST endpoints so a React (or other) frontend can call
the Python backend without going through Streamlit.
"""
# ruff: noqa: E402

import errno
import asyncio
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Literal
from contextlib import asynccontextmanager
from uuid import uuid4

# Ensure project root is on path (for uvicorn app.api:app)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from tenacity import RetryError

from app.auth_routes import router as auth_router
from app.auth_service import decode_access_token
from app.db import (
    create_pool,
    count_user_projects,
    create_project,
    delete_project,
    fetch_user_activity,
    FREE_PROJECT_LIMIT,
    get_project,
    get_user_projects,
    get_user_github_token,
    init_schema,
    record_git_push,
    record_issue_analysis,
    record_tech_stack_search,
    rename_project,
    save_user_github_token,
    update_project_selected_issue,
    update_project_code_locator,
    update_project_briefing,
    update_project_testing,
    update_project_analysis_result,
    list_users_admin,
    list_projects_admin,
)

from integrations.github_client import GitHubClient
from integrations.groq_client import GroqClient, MODEL_LLAMA_4_SCOUT_17B, MODEL_README_SUMMARY

# In-process README LLM summaries (avoid re-generating on every dashboard visit)
_readme_summary_cache: dict[str, tuple[str, float]] = {}
README_SUMMARY_CACHE_TTL_SEC = 86400.0
from core.orchestrator import ScoutOrchestrator, MAX_QA_RETRIES
from core.audit import audit_repository
from core.agents.pathfinder import PathfinderAgent
from core.terminal_manager import (
    SessionNotFoundError,
    TerminalManager,
    TerminalManagerError,
    TerminalNotFoundError,
)
from utils.cache import CacheManager
from utils.pdf_generator import PDFGenerator

from core.identity import UserContext, get_current_user
from core.memory.hindsight_client import get_scout_hindsight
from core.runtime.cascadeflow_init import (
    cascadeflow_budget_run,
    cascadeflow_session_payload,
    configure_cascadeflow_from_env,
    default_budget_usd,
)
from core.runtime.groq_context import reset_groq_step_index, set_pipeline_run_context

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_cascadeflow_from_env()
    try:
        app.state.db_pool = create_pool()
        init_schema(app.state.db_pool)
        app.state.db_init_error = None
    except Exception as e:
        app.state.db_pool = None
        app.state.db_init_error = str(e)

    app.state.terminal_manager = TerminalManager()

    yield

    pool = getattr(app.state, "db_pool", None)
    if pool is not None:
        pool.close()

    terminal_manager = getattr(app.state, "terminal_manager", None)
    if terminal_manager is not None:
        terminal_manager.close_all()


app = FastAPI(
    title="Open Source Scout API",
    description="Backend API for the Open Source Scout editor and analysis tools",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(auth_router)

# Build CORS origins list from env (supports production Railway URL)
_default_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:5175",
]
_extra = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
_frontend_url = (os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
if _frontend_url and _frontend_url not in _extra:
    _extra.append(_frontend_url)
_env_label = (os.getenv("APP_ENV") or os.getenv("RAILWAY_ENVIRONMENT") or "").lower()
_is_production = _env_label in ("production", "prod")
if _is_production and _extra:
    _allowed_origins = list(dict.fromkeys(_extra))
elif _is_production:
    logger.warning(
        "Production environment detected but ALLOWED_ORIGINS/FRONTEND_URL unset; "
        "using localhost CORS defaults"
    )
    _allowed_origins = list(dict.fromkeys(_default_origins))
else:
    _allowed_origins = list(dict.fromkeys(_default_origins + _extra))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/Response models ---


from core.agents.code_review_agent import CodeReviewAgent
from core.agents.testing_agent import TestingAgent
from core.schemas import GitHubIssue, Agent1Output, GitHubRepo, CodeReviewOutput


class PushFileRequest(BaseModel):
    """Request body for pushing file content."""

    file_path: str
    content: str
    branch_name: str
    commit_message: str
    base_branch: str = "main"
    target_mode: str | None = None  # 'original' | 'fork' | 'auto' (default)


class PushFilesRequest(BaseModel):
    """Request body for pushing multiple files in one commit."""

    files: list[dict]  # each: { file_path: str, content: str }
    branch_name: str
    commit_message: str
    base_branch: str = "main"
    target_mode: str | None = None  # 'original' | 'fork' | 'auto' (default)


class ReviewAndPushRequest(BaseModel):
    """Request body for the new review and push functionality."""

    review_files: list[dict[str, str]]  # Each: { 'path': str, 'original': str, 'modified': str }
    target_issue: GitHubIssue  # The selected GitHub issue
    briefing_markdown: str  # The briefing report
    branch_name: str
    commit_message: str
    base_branch: str = "main"
    target_mode: str | None = None  # 'original' | 'fork' | 'auto' (default)


class AnalyzeRequest(BaseModel):
    """Request body for running analysis."""

    repo_url: str
    beginner_only: bool = True
    fast_model: str = "openai/gpt-oss-120b"
    powerful_model: str = "llama-3.3-70b"
    cascadeflow_budget_usd: float | None = None


class SearchReposRequest(BaseModel):
    """Request body for personalized repository search."""

    tech_stack: list[str] = []
    search_prompt: str = ""
    fast_model: str = MODEL_LLAMA_4_SCOUT_17B
    cascadeflow_budget_usd: float | None = None
    fresh: bool = True
    client_request_id: str = ""
    exclude_repo_urls: list[str] = []


class ExportPdfRequest(BaseModel):
    """Request body for PDF export."""

    content: str
    title: str | None = None


class AuditRepoRequest(BaseModel):
    """Request body for a repository health audit."""

    repo_url: str


class ReAnalyzeRequest(BaseModel):
    """Request body for re-running phases 2+3 for a specific issue."""

    repo_url: str
    issue_number: int
    fast_model: str = "openai/gpt-oss-120b"
    powerful_model: str = "llama-3.3-70b"
    pathfinder_output: dict | None = None
    cascadeflow_budget_usd: float | None = None


class RepoSelectionFeedback(BaseModel):
    repo_url: str
    action: Literal["selected", "skipped"]


class IssueInteractionFeedback(BaseModel):
    issue_url: str
    action: Literal["opened", "skipped", "completed"]


class ExportFeedback(BaseModel):
    briefing_id: str
    format: Literal["pdf", "md", "push"]


class ThumbsFeedback(BaseModel):
    target_type: Literal["repo", "issue", "briefing"]
    target_id: str
    vote: Literal["up", "down"]


class CreateProjectRequest(BaseModel):
    """Request body for creating a new project."""

    name: str
    project_type: str  # 'tech_stack' or 'repo_url'
    tech_stack: list[str] | None = None
    repo_url: str | None = None
    repo_full_name: str | None = None
    selected_issue_number: int | None = None
    selected_issue_title: str | None = None
    analysis_result: dict | None = None


class RenameProjectRequest(BaseModel):
    """Request body for renaming a project."""

    name: str


class FileTreeRequest(BaseModel):
    """Request body for fetching files with analysis metadata."""

    ref: str = "HEAD"
    analysis_data: dict | None = None  # Optional: contains agent2_output, agent3_output
    max_files: int = 500


class ForkChoiceRequest(BaseModel):
    """Request body for fork choice confirmation."""

    choice: str  # 'fork' or 'original'
    issue_number: int | None = None
    analysis_id: str | None = None


class TerminalCreateSessionRequest(BaseModel):
    """Create a workspace-backed terminal session for a repository."""

    owner: str
    repo: str
    ref: str = "HEAD"
    analysis_data: dict[str, Any] | None = None


class TerminalCreateTabRequest(BaseModel):
    """Create one terminal tab inside an existing session."""

    label: str | None = None
    cwd: str | None = None


class TerminalSyncFilesRequest(BaseModel):
    """Sync edited files from browser state into session workspace."""

    files: list[dict[str, Any]]


class TerminalRunSuggestedRequest(BaseModel):
    """Run one command from the suggestion feed."""

    terminal_id: str
    command: str
    cwd: str | None = None


class TerminalRunCommandRequest(BaseModel):
    """Run one manual command in an existing terminal tab."""

    terminal_id: str
    command: str
    cwd: str | None = None


def _to_jsonable(obj):
    """Convert Pydantic models and nested structures to JSON-serializable values."""
    return jsonable_encoder(obj)


def _pipeline_testing_output(testing_output):
    """Strip Code Reviewer from pipeline QA — that agent is editor-only."""
    if testing_output is None:
        return None

    data = jsonable_encoder(testing_output)
    if not isinstance(data, dict):
        return data

    agent_results = [
        result
        for result in data.get("agent_results", [])
        if result.get("agent_name") != "Code Reviewer"
    ]
    if len(agent_results) == len(data.get("agent_results", [])):
        return data

    data = {**data, "agent_results": agent_results}
    if agent_results:
        data["overall_score"] = sum(result["score"] for result in agent_results) // len(agent_results)
        data["overall_passed"] = all(result["passed"] for result in agent_results)
        data["retry_agents"] = [
            result["agent_name"] for result in agent_results if not result["passed"]
        ]
        data["retry_recommended"] = not data["overall_passed"]
    return data


def _optional_user_id(request: Request) -> int | None:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    try:
        claims = decode_access_token(token)
        return int(claims.get("sub"))
    except Exception:
        return None


def _require_user_id(request: Request) -> int:
    """Extract user ID from Bearer token or raise 401."""
    uid = _optional_user_id(request)
    if uid is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return uid


def _require_pool(request: Request):
    """Return the database pool or raise 500."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return pool


def _require_admin_user(request: Request) -> int:
    """Ensure the caller is an admin user (JWT required)."""
    uid = _require_user_id(request)
    pool = _require_pool(request)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select role from users where id = %s", (uid,))
            row = cur.fetchone()
            role = row[0] if row else None
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return uid


def _user_is_admin(request: Request) -> bool:
    """Return True when the authenticated user has admin role."""
    uid = _optional_user_id(request)
    if uid is None:
        return False
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return False
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select role from users where id = %s", (uid,))
                row = cur.fetchone()
                return row is not None and row[0] == "admin"
    except Exception:
        return False


def _require_terminal_manager(request: Request) -> TerminalManager:
    """Return terminal manager or raise 503 if unavailable."""
    manager = getattr(request.app.state, "terminal_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Terminal runtime is unavailable")
    return manager


def _raise_terminal_http_error(exc: Exception) -> None:
    if isinstance(exc, SessionNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TerminalNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TerminalManagerError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=500, detail=str(exc))


def _get_github_token_for_user(request: Request) -> str | None:
    """
    Get the GitHub token for the current user.
    Falls back to .env token if user is not authenticated or has no token.
    """
    uid = _optional_user_id(request)
    if uid:
        pool = getattr(request.app.state, "db_pool", None)
        if pool:
            try:
                token = get_user_github_token(pool, uid)
                if token:
                    return token
            except Exception:
                pass
    return os.getenv("GITHUB_TOKEN")


class SaveGitHubTokenRequest(BaseModel):
    token: str


@app.post("/api/user/github-token")
def save_github_token(body: SaveGitHubTokenRequest, request: Request):
    """
    Save or update the authenticated user's GitHub Personal Access Token.
    The token is validated against the GitHub API before saving.
    """
    uid = _require_user_id(request)
    pool = _require_pool(request)

    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token cannot be empty")

    # Validate the token against GitHub and check it has public_repo scope
    import requests as _requests
    try:
        probe = _requests.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "Open-Source-Scout/1.0",
            },
            timeout=10,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach GitHub: {e}")

    if probe.status_code == 401:
        raise HTTPException(status_code=400, detail="Invalid GitHub token. Please check it and try again.")
    if not probe.ok:
        raise HTTPException(status_code=400, detail=f"GitHub rejected the token (HTTP {probe.status_code}).")

    # X-OAuth-Scopes lists what the token is allowed to do
    scopes = {s.strip() for s in probe.headers.get("X-OAuth-Scopes", "").split(",") if s.strip()}
    gh_login = probe.json().get("login", "")

    has_repo_access = bool(scopes & {"repo", "public_repo"})
    scope_warning = None
    if not has_repo_access:
        scope_warning = (
            "Token saved, but it is missing the 'public_repo' (or 'repo') scope. "
            "Forking repositories will fail until you regenerate the token with that scope."
        )

    save_user_github_token(pool, uid, token)
    return {
        "ok": True,
        "github_login": gh_login,
        "scopes": sorted(scopes),
        "has_fork_access": has_repo_access,
        "warning": scope_warning,
    }


def _safe_record_activity(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception as e:
        logger.warning("Failed to record user activity: %s", e)


def _feedback_repo_selection_worker(user_id: str, repo_url: str, action: str) -> None:
    try:
        hx = get_scout_hindsight()
        hx.retain_sync(
            user_id,
            f"Pathfinder ranking: user {action} repository {repo_url}",
            "experience",
            {"kind": "repo_selection", "repo_url": repo_url, "action": action},
        )
    except Exception as e:
        logger.warning("feedback repo-selection retain failed: %s", e)


def _feedback_issue_interaction_worker(user_id: str, issue_url: str, action: str) -> None:
    try:
        hx = get_scout_hindsight()
        hx.retain_sync(
            user_id,
            f"Issue list: user {action} {issue_url}",
            "experience",
            {"kind": "issue_interaction", "issue_url": issue_url, "action": action},
        )
    except Exception as e:
        logger.warning("feedback issue-interaction retain failed: %s", e)


def _feedback_export_worker(user_id: str, briefing_id: str, fmt: str) -> None:
    try:
        hx = get_scout_hindsight()
        hx.retain_sync(
            user_id,
            f"Briefing export: user exported briefing {briefing_id} as {fmt}",
            "experience",
            {"kind": "export_briefing", "briefing_id": briefing_id, "format": fmt},
        )
    except Exception as e:
        logger.warning("feedback export retain failed: %s", e)


def _feedback_thumbs_worker(
    user_id: str,
    target_type: str,
    target_id: str,
    vote: str,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    try:
        meta = {
            "kind": "thumbs",
            "target_type": target_type,
            "target_id": target_id,
            "vote": vote,
        }
        if extra_meta:
            meta.update(extra_meta)
        hx = get_scout_hindsight()
        hx.retain_sync(
            user_id,
            f"Explicit feedback: {vote} on {target_type} {target_id}",
            "experience",
            meta,
        )
    except Exception as e:
        logger.warning("feedback thumbs retain failed: %s", e)


_GH_ISSUE_RE = re.compile(r"github\.com/([^/\s]+/[^/\s#?]+)/issues/(\d+)", re.I)
_GH_API_ISSUE_RE = re.compile(r"api\.github\.com/repos/([^/\s]+/[^/\s#?]+)/issues/(\d+)", re.I)


def _parse_issue_url(issue_url: str) -> tuple[str, int] | None:
    if not issue_url:
        return None
    match = _GH_ISSUE_RE.search(issue_url)
    if not match:
        match = _GH_API_ISSUE_RE.search(issue_url)
    if not match:
        return None
    repo_id, issue_number = match.group(1).strip(), match.group(2).strip()
    if not repo_id or not issue_number.isdigit():
        return None
    return f"https://github.com/{repo_id}", int(issue_number)


def _record_phase1_issue_analysis(pool, user_id: int, body: AnalyzeRequest, results: dict) -> None:
    if not results.get("success") or not results.get("agent1_output") or not results.get("repo"):
        return
    a1 = results["agent1_output"]
    repo = results["repo"]
    num = a1.selected_issue_number
    if num == 0 and a1.ranked_issues:
        num = a1.ranked_issues[0].number
    title = None
    for ri in a1.ranked_issues:
        if ri.number == num:
            title = ri.title
            break
    if title is None:
        title = ""
    full_name = repo.full_name
    record_issue_analysis(
        pool,
        user_id,
        repo_url=body.repo_url.strip(),
        repo_full_name=full_name,
        issue_number=num,
        issue_title=title,
    )


# --- Endpoints ---


@app.post("/api/repos/{owner}/{repo}/review-and-push")
def review_and_push(
    request: Request,
    owner: str,
    repo: str,
    body: ReviewAndPushRequest,
    user_ctx: UserContext = Depends(get_current_user),
):
    """
    Performs a learning-focused code review and returns feedback.
    The actual push to GitHub is handled by the frontend after receiving feedback.
    """
    try:
        logger.info(f"Review and Push request received for {owner}/{repo}")

        # Instantiate the Learning Reviewer agent (CodeReviewAgent alias)
        groq_client = GroqClient.for_agent("Learning Reviewer")
        review_agent = CodeReviewAgent(groq_client)

        # Run the agent with the provided data
        review_feedback = review_agent.run(
            review_files=body.review_files,
            target_issue=body.target_issue,
            briefing_markdown=body.briefing_markdown,
        )
        code_review_output = CodeReviewOutput.model_validate(review_feedback)

        github_repo = GitHubRepo(
            full_name=f"{owner}/{repo}",
            html_url=f"https://github.com/{owner}/{repo}",
            clone_url=f"https://github.com/{owner}/{repo}.git",
            default_branch=body.base_branch or "main",
        )
        testing_agent = TestingAgent(groq_client)
        code_reviewer_qa = testing_agent.score_code_reviewer(
            repo=github_repo,
            issue=body.target_issue,
            code_review_output=code_review_output,
        )

        logger.info(f"Code review completed for {owner}/{repo}")
        payload = dict(review_feedback)
        payload["code_reviewer_qa"] = code_reviewer_qa.model_dump()
        return payload
    except Exception as e:
        logger.error(f"Error during code review for {owner}/{repo}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _enforce_free_tier_quota(request: Request):
    """Raise 403 if user has hit the free tier project limit."""
    uid = _optional_user_id(request)
    pool = getattr(request.app.state, "db_pool", None)
    if uid and pool:
        try:
            if count_user_projects(pool, uid) >= FREE_PROJECT_LIMIT:
                raise HTTPException(
                    status_code=403, 
                    detail=f"Free plan limit reached ({FREE_PROJECT_LIMIT} projects max). Please delete a project to run a new analysis or search."
                )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            logger.error("Failed to check project quota: %s", e)


@app.post("/api/analyze")
def run_analyze(
    body: AnalyzeRequest,
    request: Request,
    user_ctx: UserContext = Depends(get_current_user),
):
    """
    Run the full 3-agent analysis pipeline.

    Blocks until complete (may take 1–2 minutes). Returns analysis results.
    """
    _enforce_free_tier_quota(request)
    try:
        budget_usd = (
            body.cascadeflow_budget_usd
            if body.cascadeflow_budget_usd is not None
            else default_budget_usd()
        )
        reset_groq_step_index()
        set_pipeline_run_context(uuid4().hex[:12], user_ctx.user_id)
        with cascadeflow_budget_run(budget_usd) as cascade_session:
            github_client = GitHubClient(token=_get_github_token_for_user(request))
            cache_manager = CacheManager()
            orchestrator = ScoutOrchestrator(
                github_client=github_client,
                cache_manager=cache_manager,
                fast_model=body.fast_model,
                powerful_model=body.powerful_model,
            )
            results = orchestrator.run_phase1(
                repo_url=body.repo_url,
                beginner_only=body.beginner_only,
            )
            pool = getattr(request.app.state, "db_pool", None)
            uid = _optional_user_id(request)
            if pool and uid:
                _safe_record_activity(_record_phase1_issue_analysis, pool, uid, body, results)
            payload = _to_jsonable(results)
            if isinstance(payload, dict):
                payload["cascadeflow_run"] = cascadeflow_session_payload(cascade_session)
            return payload
    except RetryError as e:
        status_msg = str(e)
        if "RateLimitError" in status_msg or "rate limit" in status_msg.lower():
            raise HTTPException(status_code=429, detail="API rate limit exceeded. Please try again later or configure a new API key.")
        raise HTTPException(status_code=500, detail=f"LLM request failed after retries: {status_msg}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/re-analyze-issue")
def re_analyze_issue(
    body: ReAnalyzeRequest,
    request: Request,
    user_ctx: UserContext = Depends(get_current_user),
):
    """
    Re-run phases 2 (Archaeologist) + 3 (Senior Dev) for a specific issue.

    Called when the user selects a different issue from the ranked list.
    Re-uses already-fetched repo/issue data so only the LLM-heavy steps
    (code search + briefing generation) are repeated.
    """
    try:
        budget_usd = (
            body.cascadeflow_budget_usd
            if body.cascadeflow_budget_usd is not None
            else default_budget_usd()
        )
        reset_groq_step_index()
        set_pipeline_run_context(uuid4().hex[:12], user_ctx.user_id)
        with cascadeflow_budget_run(budget_usd) as cascade_session:
            github_client = GitHubClient(token=_get_github_token_for_user(request))
            orchestrator = ScoutOrchestrator(
                github_client=github_client,
                fast_model=body.fast_model,
                powerful_model=body.powerful_model,
            )

            # Fetch repo metadata
            logger.info("re-analyze: fetching repo %s", body.repo_url)
            repo = github_client.get_repo(body.repo_url)
    
            # Fetch the specific issue directly by number — works for any issue
            # regardless of how recently it was updated (avoids the "top 50" limit).
            try:
                logger.info("re-analyze: fetching issue %s", body.issue_number)
                target_issue = github_client.get_issue(body.repo_url, body.issue_number)
            except Exception:
                raise HTTPException(
                    status_code=404,
                    detail=f"Issue #{body.issue_number} not found in the repository."
                )
    
            # Also fetch a batch of issues for scoring/ranking context (phase 3)
            issues = github_client.get_issues(body.repo_url, beginner_only=False, max_issues=50)
    
            # Phase 2 — Archaeologist
            logger.info("re-analyze: running Phase 2")
            phase2 = orchestrator.run_phase2(body.repo_url, target_issue)
            logger.info("re-analyze: Phase 2 finished")
            if not phase2.get("success"):
                logger.error("re-analyze Phase 2 failed: %s", phase2.get("error"))
                raise HTTPException(status_code=500, detail=phase2.get("error", "Phase 2 failed"))
    
            agent2_output = phase2["agent2_output"]
    
            # Fetch agent1_output from a fresh issue ranking (needed for phase 3 context)
            from core.schemas import Agent1Output, RepoInfo, RankedIssue
            from core.scoring import IssueScorer
            logger.info("re-analyze: ranking context issues")
            scorer = IssueScorer()
            ranked = scorer.rank_issues(issues, top_n=3)
            logger.info("re-analyze: ranking context issues done")

            # Ensure target_issue is in the ranked list for QA structural validation
            ranked_nums = {iss.number for iss, _ in ranked}
            if target_issue.number not in ranked_nums:
                target_score = scorer.score_issue(target_issue)
                if len(ranked) >= 3:
                    ranked[2] = (target_issue, target_score)
                else:
                    ranked.append((target_issue, target_score))

            ranked_issues = [
                RankedIssue(
                    number=iss.number,
                    title=iss.title,
                    url=iss.html_url,
                    labels=iss.labels,
                    score_total=sr.total,
                    score_breakdown=sr.breakdown,
                    why=sr.reasons[:4],
                    body=iss.body,
                    created_at=iss.created_at,
                    updated_at=iss.updated_at,
                    comments=iss.comments,
                )
                for iss, sr in ranked
            ]
            agent1_output = Agent1Output(
                repo=RepoInfo(
                    url=repo.html_url,
                    default_branch=repo.default_branch,
                    description=repo.description,
                    languages=list(repo.languages.keys())[:5] if repo.languages else None,
                ),
                ranked_issues=ranked_issues,
                selected_issue_number=target_issue.number,
            )
    
            # Phase 3 — Senior Dev
            logger.info("re-analyze: running Phase 3")
            phase3 = orchestrator.run_phase3(repo, target_issue, agent1_output, agent2_output)
            logger.info("re-analyze: Phase 3 finished")
            if not phase3.get("success"):
                raise HTTPException(status_code=500, detail=phase3.get("error", "Phase 3 failed"))
    
            agent3_output = phase3["agent3_output"]
    
            # Reconstruct PathfinderOutput if provided by frontend
            pathfinder = None
            if body.pathfinder_output:
                from core.schemas import PathfinderOutput
                try:
                    pathfinder = PathfinderOutput.model_validate(body.pathfinder_output)
                except Exception:
                    pass
    
            # Phase 4 — Testing Agent with QA feedback loop (admin only; users get one pass)
            max_qa_retries = MAX_QA_RETRIES if _user_is_admin(request) else 0
            logger.info(
                "re-analyze: running QA cycle (max_retries=%d, admin=%s)",
                max_qa_retries,
                max_qa_retries > 0,
            )
            testing_result = orchestrator.run_testing(
                repo=repo,
                issue=target_issue,
                agent1_output=agent1_output,
                agent2_output=agent2_output,
                agent3_output=agent3_output,
                repo_path=phase2.get("repo_path"),
                file_tree=phase2.get("file_tree"),
                pathfinder_output=pathfinder,
                max_qa_retries=max_qa_retries,
            )
            if not testing_result.get("success"):
                raise HTTPException(
                    status_code=500,
                    detail=testing_result.get("error", "Testing / QA phase failed"),
                )
    
            final_agent2 = testing_result.get("agent2_output", agent2_output)
            final_agent3 = testing_result.get("agent3_output", agent3_output)
    
            logger.info("re-analyze: completed successfully")
            payload = {
                "success": True,
                "target_issue": target_issue,
                "agent2_output": final_agent2,
                "agent3_output": final_agent3,
                "testing_output": _pipeline_testing_output(testing_result.get("testing_output")),
            }
            pool = getattr(request.app.state, "db_pool", None)
            uid = _optional_user_id(request)
            if pool and uid:
                _safe_record_activity(
                    record_issue_analysis,
                    pool,
                    uid,
                    repo_url=body.repo_url.strip(),
                    repo_full_name=repo.full_name,
                    issue_number=target_issue.number,
                    issue_title=target_issue.title,
                )
            payload["cascadeflow_run"] = cascadeflow_session_payload(cascade_session)
            return _to_jsonable(payload)

    except RetryError as e:
        status_msg = str(e)
        if "RateLimitError" in status_msg or "rate limit" in status_msg.lower():
            raise HTTPException(
                status_code=429, 
                detail="Groq API rate limit exceeded. The analysis service is busy. Please wait a moment and try again, or update your API key for higher rate limits."
            )
        raise HTTPException(status_code=500, detail=f"LLM request failed after retries: {status_msg}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in re-analyze")
        detail = str(e)
        if isinstance(e, OSError) and getattr(e, "errno", None) == errno.EINVAL:
            detail = (
                f"{detail} — On Windows, stop other uvicorn/Python on :8001, start API on port 8003 "
                "(.\\run-backend.ps1), then: $env:OSS_API_PROXY_TARGET='http://localhost:8003'; npm run dev "
                "in frontend. See Open-Source-Scout\\run-backend.ps1."
            )
        raise HTTPException(status_code=500, detail=detail)


@app.post("/api/search-repos")
def search_repos_by_tech_stack(
    body: SearchReposRequest,
    request: Request,
    user_ctx: UserContext = Depends(get_current_user),
):
    """
    Search and rank GitHub repositories from tech tags and/or a natural-language prompt.

    Uses Pathfinder to parse preferences and return top ranked repositories.
    """
    _enforce_free_tier_quota(request)
    try:
        prompt = (body.search_prompt or "").strip()
        stack = [t.strip() for t in (body.tech_stack or []) if t and t.strip()]
        if not prompt and not stack:
            raise HTTPException(
                status_code=400,
                detail="Provide a search prompt and/or at least one technology tag",
            )

        budget_usd = (
            body.cascadeflow_budget_usd
            if body.cascadeflow_budget_usd is not None
            else default_budget_usd()
        )
        reset_groq_step_index()
        set_pipeline_run_context(uuid4().hex[:12], user_ctx.user_id)
        with cascadeflow_budget_run(budget_usd) as cascade_session:
            github_client = GitHubClient(token=_get_github_token_for_user(request))
            pathfinder = PathfinderAgent(
                GroqClient.for_agent("Pathfinder"), model=body.fast_model
            )
            results = pathfinder.run(
                tech_stack=stack,
                search_prompt=prompt,
                github_client=github_client,
                top_n=5,
                client_request_id=(body.client_request_id or "").strip(),
                exclude_repo_urls=body.exclude_repo_urls or [],
            )
            pool = getattr(request.app.state, "db_pool", None)
            uid = _optional_user_id(request)
            if pool and uid:
                names = [r.full_name for r in results.ranked_repos]
                prefs_payload = (
                    results.preferences.model_dump()
                    if results.preferences is not None
                    else None
                )
                _safe_record_activity(
                    record_tech_stack_search,
                    pool,
                    uid,
                    list(results.tech_stack),
                    names,
                    search_prompt=(results.search_prompt or "").strip() or None,
                    preferences=prefs_payload,
                )
            payload = _to_jsonable(results)
            if isinstance(payload, dict):
                payload["cascadeflow_run"] = cascadeflow_session_payload(cascade_session)
            return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/feedback/repo-selection")
def feedback_repo_selection(
    body: RepoSelectionFeedback,
    user_ctx: UserContext = Depends(get_current_user),
):
    _feedback_repo_selection_worker(user_ctx.user_id, body.repo_url.strip(), body.action)
    return {"accepted": True}


@app.post("/api/feedback/issue-interaction")
def feedback_issue_interaction(
    body: IssueInteractionFeedback,
    user_ctx: UserContext = Depends(get_current_user),
):
    _feedback_issue_interaction_worker(user_ctx.user_id, body.issue_url.strip(), body.action)
    return {"accepted": True}


@app.post("/api/feedback/export")
def feedback_export(
    body: ExportFeedback,
    user_ctx: UserContext = Depends(get_current_user),
):
    _feedback_export_worker(user_ctx.user_id, body.briefing_id.strip(), body.format)
    return {"accepted": True}


@app.post("/api/feedback/thumbs")
def feedback_thumbs(
    body: ThumbsFeedback,
    request: Request,
    user_ctx: UserContext = Depends(get_current_user),
):
    extra_meta: dict[str, Any] = {}
    target_type = body.target_type
    target_id = body.target_id.strip()
    if body.vote == "down":
        try:
            github_client = GitHubClient(token=_get_github_token_for_user(request))
            if target_type == "repo":
                repo = github_client.get_repo(target_id)
                extra_meta.update(
                    {
                        "repo_url": repo.html_url,
                        "repo_full_name": repo.full_name,
                        "language": repo.language,
                        "topics": getattr(repo, "topics", []) or [],
                    }
                )
            elif target_type == "issue":
                parsed = _parse_issue_url(target_id)
                if parsed:
                    repo_url, issue_number = parsed
                    issue = github_client.get_issue(repo_url, issue_number)
                    repo_full_name = repo_url.replace("https://github.com/", "").strip("/")
                    extra_meta.update(
                        {
                            "repo_url": repo_url,
                            "repo_full_name": repo_full_name,
                            "issue_url": issue.html_url,
                            "issue_number": issue.number,
                            "title": issue.title,
                            "labels": issue.labels or [],
                        }
                    )
        except Exception as e:
            logger.warning("thumbs feedback enrichment skipped: %s", e)

    _feedback_thumbs_worker(user_ctx.user_id, target_type, target_id, body.vote, extra_meta or None)
    return {"accepted": True}


@app.get("/api/memory/summary")
def memory_summary(
    user_ctx: UserContext = Depends(get_current_user),
    refresh_mental_models: bool = Query(False),
):
    hx = get_scout_hindsight()
    payload = hx.memory_summary_sync(
        user_ctx.user_id,
        refresh_mental_models=refresh_mental_models,
    )
    t = payload.get("totals") or {}
    try:
        total_mem = int(t.get("facts", 0)) + int(t.get("observations", 0)) + int(t.get("mental_models", 0))
    except (TypeError, ValueError):
        total_mem = 0
    if isinstance(payload, dict):
        payload = dict(payload)
        pt = dict(t)
        pt["total_entries"] = total_mem
        payload["totals"] = pt
        payload["bank_id"] = user_ctx.bank_id
        payload["hindsight_enabled"] = hx.enabled
        payload["user_id"] = user_ctx.user_id
    return payload


@app.get("/api/memory/graph")
def memory_graph(
    user_ctx: UserContext = Depends(get_current_user),
    limit: int = Query(120, ge=10, le=500),
    memory_type: str | None = Query(None, alias="type"),
):
    hx = get_scout_hindsight()
    hx.get_or_create_bank_sync(user_ctx.user_id)
    payload = hx.memory_graph_sync(user_ctx.user_id, limit=limit, memory_type=memory_type)
    if isinstance(payload, dict):
        payload = dict(payload)
        payload["hindsight_enabled"] = hx.enabled
        payload["bank_id"] = user_ctx.bank_id
    return payload


@app.get("/api/memory/by-ids")
def memory_by_ids(
    ids: str = Query(..., description="Comma-separated memory IDs"),
    user_ctx: UserContext = Depends(get_current_user),
):
    id_list = [x.strip() for x in ids.split(",") if x.strip()]
    if len(id_list) > 80:
        raise HTTPException(status_code=400, detail="Too many ids (max 80)")
    hx = get_scout_hindsight()
    rows = hx.fetch_memory_sync(user_ctx.user_id, id_list)
    return {"memories": rows}


@app.post("/api/memory/reset")
def memory_reset(
    confirm: bool = Query(False),
    user_ctx: UserContext = Depends(get_current_user),
):
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Memory reset requires query parameter confirm=true",
        )
    hx = get_scout_hindsight()
    hx.reset_bank_sync(user_ctx.user_id)
    return Response(status_code=204)


def _extract_cascadeflow_run(analysis_result: Any) -> dict[str, Any] | None:
    if not analysis_result:
        return None
    if isinstance(analysis_result, str):
        try:
            analysis_result = json.loads(analysis_result)
        except Exception:
            return None
    if not isinstance(analysis_result, dict):
        return None
    run = analysis_result.get("cascadeflow_run") or analysis_result.get("cascadeflowRun")
    return run if isinstance(run, dict) else None


@app.get("/api/admin/users")
def admin_users(
    request: Request,
    query: str | None = Query(None),
):
    _require_admin_user(request)
    pool = _require_pool(request)
    users = list_users_admin(pool, query=query)
    return {"users": users}


@app.get("/api/admin/decision-traces")
def admin_decision_traces(
    request: Request,
    user_id: int | None = Query(None),
):
    _require_admin_user(request)
    pool = _require_pool(request)
    rows = list_projects_admin(pool, user_id=user_id)
    out = []
    for row in rows:
        cascadeflow_run = _extract_cascadeflow_run(row.get("analysis_result"))
        out.append(
            {
                "project_id": row.get("id"),
                "project_name": row.get("name"),
                "project_type": row.get("project_type"),
                "repo_url": row.get("repo_url"),
                "repo_full_name": row.get("repo_full_name"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "user_id": row.get("user_id"),
                "user_email": row.get("user_email"),
                "user_display_name": row.get("user_display_name"),
                "cascadeflow_run": cascadeflow_run,
            }
        )
    return {"projects": out}


@app.get("/api/admin/memory/summary")
def admin_memory_summary(
    request: Request,
    user_id: str = Query(..., description="Target user id"),
    refresh_mental_models: bool = Query(False),
):
    _require_admin_user(request)
    hx = get_scout_hindsight()
    payload = hx.memory_summary_sync(
        user_id,
        refresh_mental_models=refresh_mental_models,
    )
    t = payload.get("totals") or {}
    try:
        total_mem = int(t.get("facts", 0)) + int(t.get("observations", 0)) + int(t.get("mental_models", 0))
    except (TypeError, ValueError):
        total_mem = 0
    if isinstance(payload, dict):
        payload = dict(payload)
        pt = dict(t)
        pt["total_entries"] = total_mem
        payload["totals"] = pt
        payload["user_id"] = user_id
        payload["hindsight_enabled"] = hx.enabled
        payload["bank_id"] = hx.bank_for_user(user_id)
    return payload


@app.get("/api/admin/memory/graph")
def admin_memory_graph(
    request: Request,
    user_id: str = Query(..., description="Target user id"),
    limit: int = Query(120, ge=10, le=500),
    memory_type: str | None = Query(None, alias="type"),
):
    _require_admin_user(request)
    hx = get_scout_hindsight()
    hx.get_or_create_bank_sync(user_id)
    payload = hx.memory_graph_sync(user_id, limit=limit, memory_type=memory_type)
    if isinstance(payload, dict):
        payload = dict(payload)
        payload["user_id"] = user_id
        payload["hindsight_enabled"] = hx.enabled
    return payload


@app.post("/api/audit-repo")
def audit_repo(
    body: AuditRepoRequest,
    request: Request,
    user_ctx: UserContext = Depends(get_current_user),
):
    """
    Run a deterministic health audit over an entire repository.

    Clones the repo, scans for technical-debt markers and debug artifacts, and
    returns a readiness score, pass/fail gate, severity breakdown, and findings.
    No LLM calls are made.
    """
    repo_url = (body.repo_url or "").strip()
    if not repo_url:
        raise HTTPException(status_code=400, detail="repo_url is required")

    try:
        github_client = GitHubClient(token=_get_github_token_for_user(request))
        owner, repo = github_client.parse_repo_url(repo_url)
        repo_path = github_client.clone_repo(repo_url)
        file_tree = github_client.get_file_tree(repo_path)
        report = audit_repository(
            repo_url=repo_url,
            repo_full_name=f"{owner}/{repo}",
            repo_path=repo_path,
            file_tree=file_tree,
        )
        return _to_jsonable(report)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid repository URL: {e}")
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("Repository audit failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/export/pdf")
def export_pdf(body: ExportPdfRequest):
    """Generate PDF from markdown content."""
    try:
        pdf_gen = PDFGenerator()
        doc_title = (body.title or "").strip() or "Contributor Briefing Document"
        pdf_bytes = pdf_gen.markdown_to_pdf(body.content, title=doc_title)
        safe_name = re.sub(r"[^\w\-]+", "_", doc_title)[:60] or "document"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
def health():
    """Health check for load balancers / readiness probes."""
    import os

    db_pool = getattr(app.state, "db_pool", None)
    db_init_error = getattr(app.state, "db_init_error", None)
    return {
        "status": "ok",
        "db_initialized": db_pool is not None,
        "db_error": db_init_error,
        "build": os.getenv("RAILWAY_GIT_COMMIT_SHA")
        or os.getenv("GIT_COMMIT")
        or "dev",
    }


def _user_row_to_profile(pool, user: dict, user_id: int) -> dict:
    ca = user.get("created_at")
    if ca is not None and hasattr(ca, "isoformat"):
        user["created_at"] = ca.isoformat()
    activity = fetch_user_activity(pool, user_id)
    user.update(activity)
    return user


@app.get("/api/me")
def me(request: Request):
    user_id = _require_user_id(request)
    pool = _require_pool(request)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, email, display_name, role, created_at from users where id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            cols = [d.name for d in cur.description]
            user = dict(zip(cols, row, strict=False))
    return _user_row_to_profile(pool, user, user_id)


# --- Project endpoints ---


@app.get("/api/projects")
def list_projects(request: Request):
    """List all projects for the authenticated user."""
    uid = _require_user_id(request)
    pool = _require_pool(request)
    projects = get_user_projects(pool, uid)
    return {"projects": projects, "limit": FREE_PROJECT_LIMIT}


@app.post("/api/projects", status_code=201)
def create_project_endpoint(body: CreateProjectRequest, request: Request):
    """Create a new project. Enforces the free plan project limit."""
    uid = _require_user_id(request)
    pool = _require_pool(request)

    current_count = count_user_projects(pool, uid)
    if current_count >= FREE_PROJECT_LIMIT:
        raise HTTPException(
            status_code=403,
            detail=f"Free plan limit reached. You can have at most {FREE_PROJECT_LIMIT} projects. "
                   f"Delete an existing project to create a new one.",
        )

    if body.project_type not in ("tech_stack", "repo_url"):
        raise HTTPException(status_code=400, detail="project_type must be 'tech_stack' or 'repo_url'")

    project = create_project(
        pool,
        uid,
        name=body.name,
        project_type=body.project_type,
        tech_stack=body.tech_stack,
        repo_url=body.repo_url,
        repo_full_name=body.repo_full_name,
        selected_issue_number=body.selected_issue_number,
        selected_issue_title=body.selected_issue_title,
        analysis_result=body.analysis_result,
    )
    return project


@app.get("/api/projects/{project_id}")
def get_project_endpoint(project_id: int, request: Request):
    """Get a single project with its full analysis result."""
    uid = _require_user_id(request)
    pool = _require_pool(request)
    project = get_project(pool, uid, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.patch("/api/projects/{project_id}")
def rename_project_endpoint(project_id: int, body: RenameProjectRequest, request: Request):
    """Rename a project. Only the name can be changed."""
    uid = _require_user_id(request)
    pool = _require_pool(request)
    result = rename_project(pool, uid, project_id, body.name)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@app.delete("/api/projects/{project_id}")
def delete_project_endpoint(project_id: int, request: Request):
    """Delete a project."""
    uid = _require_user_id(request)
    pool = _require_pool(request)
    deleted = delete_project(pool, uid, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True}


# --- Project step persistence endpoints ---


class SelectIssueRequest(BaseModel):
    """Lock a specific issue for a project."""
    issue_number: int
    issue_title: str | None = None
    target_issue: dict | None = None


class SaveCodeLocatorRequest(BaseModel):
    """Store Agent 2 (Archaeologist) output."""
    code_locator_output: dict


class SaveBriefingRequest(BaseModel):
    """Store Agent 3 (Senior Dev) output."""
    briefing_output: dict


class SaveTestingRequest(BaseModel):
    """Store Agent 4 (Testing/QA) output."""
    testing_output: dict


@app.patch("/api/projects/{project_id}/select-issue")
def select_issue_endpoint(project_id: int, body: SelectIssueRequest, request: Request):
    """
    Lock the selected issue for a project.

    Once locked, the user cannot change the selected issue for this project.
    Returns 409 if the issue is already locked.
    """
    uid = _require_user_id(request)
    pool = _require_pool(request)
    result = update_project_selected_issue(
        pool,
        uid,
        project_id,
        issue_number=body.issue_number,
        issue_title=body.issue_title,
        target_issue=body.target_issue,
    )
    if result is None:
        # Could be not found OR already locked
        project = get_project(pool, uid, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.get("issue_locked"):
            raise HTTPException(
                status_code=409,
                detail="Issue is already locked for this project. Delete the project and create a new one to select a different issue.",
            )
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@app.patch("/api/projects/{project_id}/code-locator")
def save_code_locator_endpoint(project_id: int, body: SaveCodeLocatorRequest, request: Request):
    """Persist Agent 2 (Archaeologist) output for a project."""
    uid = _require_user_id(request)
    pool = _require_pool(request)
    result = update_project_code_locator(pool, uid, project_id, body.code_locator_output)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@app.patch("/api/projects/{project_id}/briefing")
def save_briefing_endpoint(project_id: int, body: SaveBriefingRequest, request: Request):
    """Persist Agent 3 (Senior Dev) output for a project."""
    uid = _require_user_id(request)
    pool = _require_pool(request)
    result = update_project_briefing(pool, uid, project_id, body.briefing_output)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@app.patch("/api/projects/{project_id}/testing")
def save_testing_endpoint(project_id: int, body: SaveTestingRequest, request: Request):
    """Persist Agent 4 (Testing/QA) output for a project."""
    uid = _require_user_id(request)
    pool = _require_pool(request)
    result = update_project_testing(pool, uid, project_id, body.testing_output)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


class SaveAnalysisResultRequest(BaseModel):
    """Overwrite the monolithic analysis_result JSONB."""
    analysis_result: dict


@app.patch("/api/projects/{project_id}/analysis-result")
def save_analysis_result_endpoint(project_id: int, body: SaveAnalysisResultRequest, request: Request):
    """Save the full merged analysis result back to the project."""
    uid = _require_user_id(request)
    pool = _require_pool(request)
    result = update_project_analysis_result(pool, uid, project_id, body.analysis_result)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@app.get("/api/repos/{owner}/{repo}/tree")
def get_repo_file_tree(
    request: Request,
    owner: str,
    repo: str,
    ref: str = "HEAD",
    max_files: int = 500,
):
    """
    Fetch the complete file tree structure for a repository.
    
    Returns all files and directories with metadata for building a file browser UI.
    Files that need attention (from analysis) can be marked separately.
    """
    owner = owner.strip()
    repo = repo.strip()
    try:
        client = GitHubClient(token=_get_github_token_for_user(request))
        files = client.get_repo_file_tree(owner, repo, ref=ref, max_files=max_files)
        return {
            "owner": owner,
            "repo": repo,
            "ref": ref,
            "files": files,
            "total": len(files),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/repos/{owner}/{repo}/tree/with-analysis")
def get_tree_with_analysis(
    request: Request,
    owner: str,
    repo: str,
    body: FileTreeRequest,
):
    """
    Fetch file tree merged with analysis data.
    
    Marks files that need to be changed (from Archaeologist hits and Senior Dev output).
    Highlightedfiles are weighted: 80% Archaeologist hits, 20% Senior Dev mentions.
    
    Returns:
    {
        "owner": str,
        "repo": str,
        "files": [
            {
                "path": "src/main.py",
                "type": "file" | "dir",
                "size": 1024,
                "highlighted": bool,
                "reason": str  # Why this file is highlighted
            }
        ],
        "highlighted_count": int,
        "total": int,
    }
    """
    owner = owner.strip()
    repo = repo.strip()
    try:
        client = GitHubClient(token=_get_github_token_for_user(request))
        files = client.get_repo_file_tree(owner, repo, ref=body.ref, max_files=body.max_files)
        
        # Parse analysis data to find highlighted files
        highlighted_paths = {}  # path -> reason
        
        if body.analysis_data:
            # Extract from Archaeologist hits (80% weight)
            agent2_output = body.analysis_data.get("agent2_output", {})
            if agent2_output:
                hits = agent2_output.get("hits", [])
                for hit in hits:
                    path = hit.get("path", "")  # Changed from file_path to path
                    if path:
                        reason = f"Code location: {hit.get('why_relevant', 'Referenced in analysis')}"
                        highlighted_paths[path] = reason
            
            # Extract from Senior Dev briefing (20% weight - supplementary)
            agent3_output = body.analysis_data.get("agent3_output", {})
            if agent3_output:
                briefing = agent3_output.get("briefing_markdown", "")
                # Look for common file patterns mentioned in briefing
                # (this is a simple heuristic; could be improved)
                import re
                # Match paths like src/main.py, app/api.py, etc.
                file_patterns = re.findall(r'[`\']([a-zA-Z0-9_\-./]*\.[a-zA-Z0-9_]+)[`\']', briefing)
                for pattern in file_patterns:
                    if pattern and "/" in pattern:
                        if pattern not in highlighted_paths:
                            highlighted_paths[pattern] = "Mentioned in briefing"
        
        # Merge with file tree
        result_files = []
        for file in files:
            file_path = file["path"]
            is_highlighted = file_path in highlighted_paths
            
            result_files.append({
                "path": file_path,
                "type": file["type"],
                "size": file.get("size", 0),
                "highlighted": is_highlighted,
                "reason": highlighted_paths.get(file_path, "")
            })
        
        return {
            "owner": owner,
            "repo": repo,
            "ref": body.ref,
            "files": result_files,
            "highlighted_count": sum(1 for f in result_files if f["highlighted"]),
            "total": len(result_files),
        }
    except Exception as e:
        logger.error(f"Error fetching tree with analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/repos/{owner}/{repo}/files/{file_path:path}")
def get_file_content(
    request: Request,
    owner: str,
    repo: str,
    file_path: str,
    ref: str = "HEAD",
):
    """
    Fetch raw file content from a repository.

    Uses the GitHub Contents API. Requires GITHUB_TOKEN for private repos.
    """
    try:
        client = GitHubClient(token=_get_github_token_for_user(request))
        content = client.get_file_content(owner, repo, file_path, ref=ref)
        return {"content": content, "path": file_path, "ref": ref}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _groq_client_for_readme() -> GroqClient:
    """Prefer Pathfinder key, then other agent keys, then GROQ_API_KEY."""
    for agent in ("Pathfinder", "Triage Nurse", "Senior Dev", "Archaeologist"):
        try:
            return GroqClient.for_agent(agent)
        except ValueError:
            continue
    return GroqClient()


@app.get("/api/repos/{owner}/{repo}/readme-summary")
def get_readme_summary(request: Request, owner: str, repo: str, fresh: bool = False):
    """
    Fetch repository README and generate an LLM summary.
    """
    owner = owner.strip()
    repo = repo.strip()
    cache_key = f"{owner}/{repo}".lower()
    now = time.time()
    if fresh:
        _readme_summary_cache.pop(cache_key, None)
    cached = _readme_summary_cache.get(cache_key)
    if cached is not None:
        summary_text, stored_at = cached
        if now - stored_at < README_SUMMARY_CACHE_TTL_SEC:
            return {"summary": summary_text}

    try:
        client = GitHubClient(token=_get_github_token_for_user(request))
        readme_names = ['README.md', 'readme.md', 'Readme.md', 'README.rst', 'README']
        content = None
        for name in readme_names:
            try:
                content = client.get_file_content(owner, repo, name)
                if content:
                    break
            except Exception:
                continue

        if not content:
            msg = "No README found for this repository."
            _readme_summary_cache[cache_key] = (msg, now)
            return {"summary": msg}

        groq_client = _groq_client_for_readme()
        prompt = (
            "Please summarize the following repository README into a concise and well-formatted "
            "technical overview. "
            "CRITICAL FORMATTING RULES: "
            "1. Match this exact section style using emojis and no markdown headers: 📄 Overview, ✨ Key Features, 🎯 Intended Audience, 🚀 Quick Start. "
            "2. Do NOT use markdown bullet points (like - or *). Write features as individual standalone sentences. "
            "3. You MUST use DOUBLE NEWLINES (\\n\\n) between EVERY single line, sentence, and section title. No two lines of text should touch each other. "
            f"README:\n{content[:20000]}"
        )

        from integrations.groq_client import GroqAPIError

        readme_models = [
            MODEL_README_SUMMARY,
            MODEL_LLAMA_4_SCOUT_17B,
            "openai/gpt-oss-20b",
            "llama-3.3-70b",
        ]
        summary = None
        last_err = None
        for model_id in readme_models:
            try:
                summary = groq_client.complete(
                    prompt=prompt,
                    model=model_id,
                    max_tokens=1500,
                    agent_name="Pathfinder",
                )
                break
            except GroqAPIError as e:
                last_err = e
                if "model_not_found" not in str(e).lower() and "does not exist" not in str(e).lower():
                    raise
                continue
        if summary is None:
            raise last_err or ValueError("No Groq model available for README summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("LLM returned an empty README summary")
        summary = summary.strip()
        _readme_summary_cache[cache_key] = (summary, time.time())
        return {"summary": summary}
    except RetryError as e:
        status_msg = str(e)
        if "RateLimitError" in status_msg or "rate limit" in status_msg.lower():
            raise HTTPException(status_code=429, detail="API rate limit exceeded. Please try again later.")
        raise HTTPException(status_code=500, detail=f"LLM request failed: {status_msg}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/repos/{owner}/{repo}/fork-choice")
def fork_choice(
    request: Request,
    owner: str,
    repo: str,
    body: ForkChoiceRequest,
):
    """
    Process user's choice for editing a repository.
    
    The user can choose to:
    1. Fork the repository and edit on their fork
    2. Edit directly on original (if they have access, otherwise error)
    
    Returns fork information if forking, or confirmation if using original.
    """
    owner = owner.strip()
    repo = repo.strip()
    
    try:
        client = GitHubClient(token=_get_github_token_for_user(request))
        
        if body.choice == "fork":
            # Initiate fork
            fork_info = client.fork_repo(owner, repo)
            fork_owner = fork_info["fork_owner"]
            fork_repo = fork_info["fork_repo"]
            fork_url = f"https://github.com/{fork_owner}/{fork_repo}"
            return {
                "success": True,
                "choice": "fork",
                "fork_owner": fork_owner,
                "fork_repo": fork_repo,
                "fork_url": fork_url,
                "message": f"Repository forked to {fork_owner}/{fork_repo}",
            }
        
        elif body.choice == "original":
            # Check if user has push access to original
            resp = client.session.get(f"{client.BASE_URL}/repos/{owner}/{repo}")
            resp.raise_for_status()
            permissions = resp.json().get("permissions", {})
            can_push = permissions.get("push", False)
            
            if not can_push:
                raise HTTPException(
                    status_code=403,
                    detail="You don't have push access to this repository. Please choose 'fork' instead."
                )
            
            return {
                "success": True,
                "choice": "original",
                "owner": owner,
                "repo": repo,
                "message": "Editing on original repository",
            }
        
        else:
            raise HTTPException(
                status_code=400,
                detail="Choice must be 'fork' or 'original'"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing fork choice: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/repos/{owner}/{repo}/push")
def push_file(
    request: Request,
    owner: str,
    repo: str,
    body: PushFileRequest,
):
    """
    Push edited file content to a new branch.

    Forks the repo if the user doesn't have push access, then creates
    a branch with the single-file commit. Returns branch URL and PR link.
    """
    try:
        logger.info(f"Push request: {owner}/{repo} - file: {body.file_path}")
        client = GitHubClient(token=_get_github_token_for_user(request))
        
        logger.info(f"Checking GitHub token: {'present' if client.has_token else 'MISSING'}")
        
        target_mode = (body.target_mode or "auto").strip().lower()
        # Use the multi-file implementation for the single-file case too, so
        # branch updates are consistent with the batch endpoint and honor
        # target_mode ("original"|"fork"|"auto").
        try:
            result = client.push_files_content(
                owner=owner,
                repo=repo,
                branch_name=body.branch_name,
                files=[{"file_path": body.file_path, "content": body.content}],
                commit_message=body.commit_message,
                base_branch=body.base_branch,
                target_mode=target_mode,
            )
        except PermissionError as e:
            if str(e) == "NO_PUSH_ACCESS" or "NO_PUSH_ACCESS" in str(e):
                raise HTTPException(
                    status_code=403,
                    detail="You don't have push access to this repository. Please fork before pushing.",
                )
            elif "Cannot fork" in str(e):
                raise HTTPException(status_code=403, detail=str(e))
            raise
        logger.info(f"Push successful: {result.get('branch_url')}")
        
        pool = getattr(request.app.state, "db_pool", None)
        uid = _optional_user_id(request)
        if pool and uid:
            _safe_record_activity(
                record_git_push,
                pool,
                uid,
                upstream_owner=result.get("upstream_owner") or owner,
                upstream_repo=result.get("upstream_repo") or repo,
                branch_name=result.get("branch") or body.branch_name,
                file_path=body.file_path,
                commit_sha=result.get("commit_sha"),
                pr_url=result.get("pr_url"),
                commit_message=body.commit_message,
            )
        return result
    except Exception as e:
        logger.error(f"Error pushing file to {owner}/{repo}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/repos/{owner}/{repo}/push-batch")
def push_files_batch(
    request: Request,
    owner: str,
    repo: str,
    body: PushFilesRequest,
):
    """
    Push multiple edited files to a single branch as ONE commit.

    This fixes the previous behavior where looping single-file pushes would
    force-update the branch and effectively keep only the last file.
    """
    try:
        client = GitHubClient(token=_get_github_token_for_user(request))
        target_mode = (body.target_mode or "auto").strip().lower()
        try:
            result = client.push_files_content(
                owner=owner,
                repo=repo,
                branch_name=body.branch_name,
                files=body.files,
                commit_message=body.commit_message,
                base_branch=body.base_branch,
                target_mode=target_mode,
            )
        except PermissionError as e:
            if str(e) == "NO_PUSH_ACCESS" or "NO_PUSH_ACCESS" in str(e):
                raise HTTPException(
                    status_code=403,
                    detail="You don't have push access to this repository. Please fork before pushing.",
                )
            elif "Cannot fork" in str(e):
                raise HTTPException(status_code=403, detail=str(e))
            raise

        pool = getattr(request.app.state, "db_pool", None)
        uid = _optional_user_id(request)
        if pool and uid:
            # Record a single activity row with a representative file path.
            rep_path = (body.files[0].get("file_path") if body.files else None) or ""
            _safe_record_activity(
                record_git_push,
                pool,
                uid,
                upstream_owner=result.get("upstream_owner") or owner,
                upstream_repo=result.get("upstream_repo") or repo,
                branch_name=result.get("branch") or body.branch_name,
                file_path=rep_path,
                commit_sha=result.get("commit_sha"),
                pr_url=result.get("pr_url"),
                commit_message=body.commit_message,
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pushing batch to {owner}/{repo}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Editor terminal runtime (ephemeral, local workspace only)
# ---------------------------------------------------------------------------


@app.post("/api/terminal/sessions")
def create_terminal_session(body: TerminalCreateSessionRequest, request: Request):
    """Create a new terminal workspace session for a repository."""
    manager = _require_terminal_manager(request)
    try:
        payload = manager.create_session(
            owner=body.owner,
            repo=body.repo,
            ref=body.ref,
            analysis_data=body.analysis_data,
            github_token=_get_github_token_for_user(request),
        )
        return payload
    except Exception as e:
        _raise_terminal_http_error(e)


@app.delete("/api/terminal/sessions/{session_id}")
def close_terminal_session(session_id: str, request: Request):
    """Close a terminal session and delete its workspace."""
    manager = _require_terminal_manager(request)
    try:
        manager.close_session(session_id)
        return {"ok": True}
    except Exception as e:
        _raise_terminal_http_error(e)


@app.post("/api/terminal/{session_id}/sync-files")
def terminal_sync_files(session_id: str, body: TerminalSyncFilesRequest, request: Request):
    """Sync edited browser files into the terminal workspace before running commands."""
    manager = _require_terminal_manager(request)
    try:
        result = manager.sync_files(session_id, body.files)
        return {"ok": True, **result}
    except Exception as e:
        _raise_terminal_http_error(e)


@app.post("/api/terminal/{session_id}/terminals")
def create_terminal_tab(session_id: str, body: TerminalCreateTabRequest, request: Request):
    """Create one additional terminal tab inside a session."""
    manager = _require_terminal_manager(request)
    try:
        terminal = manager.create_terminal(session_id, label=body.label, cwd=body.cwd)
        return {"ok": True, "terminal": terminal}
    except Exception as e:
        _raise_terminal_http_error(e)


@app.get("/api/terminal/{session_id}/terminals")
def list_terminal_tabs(session_id: str, request: Request):
    """List all terminals currently attached to a session."""
    manager = _require_terminal_manager(request)
    try:
        terminals = manager.list_terminals(session_id)
        return {"terminals": terminals}
    except Exception as e:
        _raise_terminal_http_error(e)


@app.get("/api/terminal/{session_id}/suggestions")
def list_terminal_suggestions(session_id: str, request: Request):
    """Return run-step suggestions inferred from the workspace."""
    manager = _require_terminal_manager(request)
    try:
        suggestions = manager.get_suggestions(session_id)
        return {"suggestions": suggestions}
    except Exception as e:
        _raise_terminal_http_error(e)


@app.post("/api/terminal/{session_id}/run-suggested")
def run_terminal_suggested_command(
    session_id: str,
    body: TerminalRunSuggestedRequest,
    request: Request,
):
    """Run exactly one suggested command in the active terminal."""
    manager = _require_terminal_manager(request)
    command = (body.command or "").strip()
    if not manager.is_allowed_suggested_command(command):
        raise HTTPException(status_code=400, detail="Suggested command is not allowed")

    try:
        result = manager.run_command(
            session_id=session_id,
            terminal_id=body.terminal_id,
            command=command,
            cwd=body.cwd,
        )
        return {"ok": True, **result}
    except Exception as e:
        _raise_terminal_http_error(e)


@app.post("/api/terminal/{session_id}/run")
def run_terminal_command(
    session_id: str,
    body: TerminalRunCommandRequest,
    request: Request,
):
    """Run one manual command in the active terminal tab."""
    manager = _require_terminal_manager(request)
    command = (body.command or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")

    try:
        result = manager.run_command(
            session_id=session_id,
            terminal_id=body.terminal_id,
            command=command,
            cwd=body.cwd,
        )
        return {"ok": True, **result}
    except Exception as e:
        _raise_terminal_http_error(e)


@app.get("/api/terminal/{session_id}/{terminal_id}/output")
def get_terminal_output(
    session_id: str,
    terminal_id: str,
    request: Request,
    max_chunks: int = 300,
):
    """Poll terminal output chunks for environments where websocket drops occur."""
    manager = _require_terminal_manager(request)
    safe_max = max(1, min(max_chunks, 1000))
    try:
        chunks = manager.read_output(session_id, terminal_id, max_chunks=safe_max)
        status = manager.get_terminal_status(session_id, terminal_id)
        return {
            "chunks": chunks,
            "closed": status.get("closed", False),
            "exit_code": status.get("exit_code"),
        }
    except Exception as e:
        _raise_terminal_http_error(e)


@app.websocket("/api/terminal/{session_id}/{terminal_id}")
async def terminal_socket(websocket: WebSocket, session_id: str, terminal_id: str):
    """Interactive terminal IO over websocket for near real-time streaming."""
    manager = getattr(websocket.app.state, "terminal_manager", None)
    await websocket.accept()

    if manager is None:
        await websocket.send_json({"type": "error", "message": "Terminal runtime is unavailable"})
        await websocket.close(code=1011)
        return

    try:
        history = manager.get_history(session_id, terminal_id)
        if history:
            await websocket.send_json({"type": "output", "data": history, "history": True})
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})
        await websocket.close(code=1008)
        return

    try:
        while True:
            chunks = manager.read_output(session_id, terminal_id)
            if chunks:
                await websocket.send_json({"type": "output", "data": "".join(chunks)})

            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=0.15)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break

            msg_type = str(message.get("type") or "").lower()
            if msg_type == "input":
                manager.send_input(session_id, terminal_id, str(message.get("data") or ""))
            elif msg_type == "command":
                manager.run_command(
                    session_id,
                    terminal_id,
                    str(message.get("command") or ""),
                    cwd=message.get("cwd"),
                )
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "close":
                break
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Unsupported message type. Use input|command|ping|close.",
                    }
                )
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        try:
            chunks = manager.read_output(session_id, terminal_id)
            if chunks:
                await websocket.send_json({"type": "output", "data": "".join(chunks)})
        except Exception:
            pass
        await websocket.close()


# ---------------------------------------------------------------------------
# Serve the built React frontend (production only)
# ---------------------------------------------------------------------------
# Mount the Vite build output so FastAPI serves the full app from one process.
# This is only active when frontend/dist exists (i.e. after `npm run build`).
# In local dev the Vite dev server handles the frontend on port 5173.

_dist_dir = project_root / "frontend" / "dist"
if _dist_dir.is_dir():
    # Serve the hashed JS/CSS chunks (e.g. /assets/index-abc123.js)
    _assets_dir = _dist_dir / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    # Serve root-level public files (e.g. /Opensource_Scout-Logo.png, /vite.svg, /favicon.ico)
    # These are files from frontend/public/ that Vite copies to dist/ root.
    # Must be mounted BEFORE the SPA catch-all so they're served as real files.
    app.mount("/static-root", StaticFiles(directory=_dist_dir), name="static-root")

    # Catch-all: serve index.html for any non-API, non-asset path so React Router works.
    @app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
    async def serve_spa(request: Request, full_path: str):
        # Try to serve the file directly from dist/ first (handles /Opensource_Scout-Logo.png etc.)
        candidate = _dist_dir / full_path
        if candidate.is_file():
            from fastapi.responses import FileResponse
            return FileResponse(str(candidate))
        # Fall back to SPA index.html for all other paths
        index = _dist_dir / "index.html"
        return HTMLResponse(
            content=index.read_text(),
            status_code=200,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
            },
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
