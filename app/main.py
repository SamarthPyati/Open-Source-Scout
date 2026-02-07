"""
Open Source Scout - Streamlit UI
A multi-agent AI assistant for finding and fixing GitHub issues.
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import streamlit as st
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

from integrations.github_client import GitHubClient
from integrations.groq_client import GroqClient
from core.orchestrator import ScoutOrchestrator
from utils.cache import CacheManager
from utils.pdf_generator import PDFGenerator


# Page configuration
st.set_page_config(
    page_title="Open Source Scout",
    page_icon="🔭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for beautiful UI
st.markdown("""
<style>
    /* Main container styling */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Header styling */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        margin-bottom: 2rem;
        text-align: center;
        color: white;
    }
    
    .main-header h1 {
        font-size: 2.5rem;
        margin-bottom: 0.5rem;
    }
    
    .main-header p {
        font-size: 1.1rem;
        opacity: 0.9;
    }
    
    /* Card styling */
    .scout-card {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 1rem;
        border-left: 4px solid #667eea;
    }
    
    /* Score badge */
    .score-badge {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 20px;
        font-weight: bold;
        display: inline-block;
    }
    
    .score-badge.medium {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    }
    
    .score-badge.low {
        background: linear-gradient(135deg, #ff6a00 0%, #ee0979 100%);
    }
    
    /* Code block styling */
    .code-snippet {
        background: #1e1e1e;
        color: #d4d4d4;
        padding: 1rem;
        border-radius: 8px;
        font-family: 'Fira Code', monospace;
        font-size: 0.85rem;
        overflow-x: auto;
    }
    
    /* Status message */
    .status-message {
        padding: 0.75rem 1rem;
        border-radius: 8px;
        margin: 0.5rem 0;
        font-weight: 500;
    }
    
    .status-message.info {
        background: #e3f2fd;
        color: #1565c0;
    }
    
    .status-message.success {
        background: #e8f5e9;
        color: #2e7d32;
    }
    
    .status-message.warning {
        background: #fff3e0;
        color: #ef6c00;
    }
    
    /* Better button styling */
    .stButton > button {
        width: 100%;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2rem;
    }
    
    .stTabs [data-baseweb="tab"] {
        padding: 1rem 2rem;
        font-weight: 600;
    }
    
    /* Sidebar styling */
    .css-1d391kg {
        padding-top: 2rem;
    }
    
    /* Expander styling */
    .streamlit-expanderHeader {
        font-weight: 600;
        font-size: 1rem;
    }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize session state variables."""
    if "results" not in st.session_state:
        st.session_state.results = None
    if "status_messages" not in st.session_state:
        st.session_state.status_messages = []
    if "running" not in st.session_state:
        st.session_state.running = False


def add_status(message: str):
    """Add a status message."""
    st.session_state.status_messages.append(message)


def render_header():
    """Render the main header."""
    st.markdown("""
    <div class="main-header">
        <h1>🔭 Open Source Scout</h1>
        <p>AI-powered assistant for finding and contributing to open-source issues</p>
    </div>
    """, unsafe_allow_html=True)


def render_sidebar():
    """Render the sidebar with inputs and options."""
    with st.sidebar:
        st.markdown("### 📝 Repository Input")
        
        repo_url = st.text_input(
            "GitHub Repository URL",
            placeholder="https://github.com/owner/repo",
            help="Enter any public GitHub repository URL"
        )
        
        st.markdown("---")
        st.markdown("### ⚙️ Options")
        
        beginner_only = st.checkbox(
            "🌱 Beginner-only mode",
            value=True,
            help="Filter for 'good first issue', 'help wanted', and similar labels"
        )
        
        # Model selection
        model_options = {
            "Recommended": ("qwen-qwq-32b", "llama-3.3-70b"),
            "Fast": ("llama-3.1-8b", "llama-3.3-70b"),
            "Balanced": ("llama-3.3-70b", "llama-3.3-70b"),
        }
        
        model_choice = st.selectbox(
            "🤖 Model Selection",
            options=list(model_options.keys()),
            index=0,
            help="Choose model configuration for analysis"
        )
        
        fast_model, powerful_model = model_options[model_choice]
        
        st.markdown("---")
        
        # API status
        st.markdown("### 📊 API Status")
        
        groq_key = os.getenv("GROQ_API_KEY")
        github_token = os.getenv("GITHUB_TOKEN")
        
        if groq_key:
            st.success("✅ Groq API connected")
        else:
            st.error("❌ Groq API key missing")
        
        if github_token:
            st.success("✅ GitHub token configured")
        else:
            st.warning("⚠️ No GitHub token (60 req/hr limit)")
        
        st.markdown("---")
        
        # Generate button
        generate_disabled = not repo_url or not groq_key
        
        if st.button(
            "🚀 Generate Analysis",
            type="primary",
            disabled=generate_disabled,
            use_container_width=True
        ):
            return {
                "action": "generate",
                "repo_url": repo_url,
                "beginner_only": beginner_only,
                "fast_model": fast_model,
                "powerful_model": powerful_model
            }
        
        # Demo repos
        st.markdown("---")
        st.markdown("### 🎯 Try Demo Repos")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("FastAPI", use_container_width=True):
                return {
                    "action": "generate",
                    "repo_url": "https://github.com/tiangolo/fastapi",
                    "beginner_only": beginner_only,  # Use checkbox value
                    "fast_model": fast_model,
                    "powerful_model": powerful_model
                }
        
        with col2:
            if st.button("httpx", use_container_width=True):
                return {
                    "action": "generate",
                    "repo_url": "https://github.com/encode/httpx",
                    "beginner_only": beginner_only,  # Use checkbox value
                    "fast_model": fast_model,
                    "powerful_model": powerful_model
                }
    
    return None


def render_issue_ranking(results: dict):
    """Render the issue ranking tab."""
    if not results or not results.get("success"):
        st.info("Run an analysis to see issue rankings")
        return
    
    agent1 = results.get("agent1_output")
    if not agent1 or not agent1.ranked_issues:
        st.warning("No issues were ranked")
        return
    
    st.markdown("### 🏆 Top Ranked Issues")
    
    for i, issue in enumerate(agent1.ranked_issues, 1):
        # Score color
        score_class = "high" if issue.score_total >= 70 else ("medium" if issue.score_total >= 50 else "low")
        
        with st.expander(f"#{i} Issue #{issue.number}: {issue.title}", expanded=(i == 1)):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.markdown(f"**[View on GitHub]({issue.url})**")
                
                if issue.labels:
                    labels_html = " ".join([f"`{label}`" for label in issue.labels])
                    st.markdown(f"**Labels:** {labels_html}")
            
            with col2:
                st.metric("Score", f"{issue.score_total}/100")
            
            # Score breakdown
            st.markdown("#### Score Breakdown")
            breakdown = issue.score_breakdown
            
            cols = st.columns(5)
            cols[0].metric("Labels", f"{breakdown.labels}/25")
            cols[1].metric("Clarity", f"{breakdown.clarity}/20")
            cols[2].metric("Activity", f"{breakdown.activity}/15")
            cols[3].metric("Size", f"{breakdown.size_estimate}/20")
            cols[4].metric("Risk", f"{breakdown.risk_penalty}")
            
            # Reasons
            st.markdown("#### Why This Issue?")
            for reason in issue.why:
                st.markdown(f"- {reason}")


def render_code_locator(results: dict):
    """Render the code locator tab."""
    if not results or not results.get("success"):
        st.info("Run an analysis to see code locations")
        return
    
    agent2 = results.get("agent2_output")
    if not agent2:
        st.warning("Code locator results not available")
        return
    
    st.markdown(f"### 🔍 Code Analysis for Issue #{agent2.issue_number}")
    
    # Confidence badge
    confidence_color = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}
    st.markdown(f"**Confidence:** {confidence_color.get(agent2.confidence, '⚪')} {agent2.confidence}")
    
    # Keywords
    if agent2.keywords:
        st.markdown("**Search Keywords:** " + ", ".join([f"`{k}`" for k in agent2.keywords]))
    
    # Call trace hint
    if agent2.call_trace_hint:
        st.markdown("**Call Trace Hint:** " + " → ".join(agent2.call_trace_hint))
    
    st.markdown("---")
    st.markdown("### 📁 Relevant Files")
    
    for i, hit in enumerate(agent2.hits, 1):
        with st.expander(f"{i}. `{hit.path}`", expanded=(i <= 3)):
            if hit.symbols:
                st.markdown("**Symbols:** " + ", ".join([f"`{s}`" for s in hit.symbols[:10]]))
            
            st.markdown(f"**Why Relevant:** {hit.why_relevant}")
            
            if hit.snippet:
                st.markdown("**Code Snippet:**")
                st.code(hit.snippet[:1500], language="python")
    
    # Additional files
    if agent2.next_files_to_check:
        st.markdown("### 📋 Additional Files to Check")
        for f in agent2.next_files_to_check:
            st.markdown(f"- `{f}`")


def render_briefing_document(results: dict):
    """Render the briefing document tab."""
    if not results or not results.get("success"):
        st.info("Run an analysis to see the briefing document")
        return
    
    agent3 = results.get("agent3_output")
    if not agent3:
        st.warning("Briefing document not available")
        return
    
    # Export buttons
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.download_button(
            "📄 Download Markdown",
            data=agent3.briefing_markdown,
            file_name="contributor_briefing.md",
            mime="text/markdown",
            use_container_width=True
        )
    
    with col2:
        # Generate PDF
        try:
            pdf_gen = PDFGenerator()
            pdf_bytes = pdf_gen.markdown_to_pdf(agent3.briefing_markdown)
            st.download_button(
                "📑 Download PDF",
                data=pdf_bytes,
                file_name="contributor_briefing.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        except Exception as e:
            st.button("📑 PDF Error", disabled=True, use_container_width=True)
    
    with col3:
        if st.button("📋 Copy PR Draft", use_container_width=True):
            pr = agent3.pr_draft
            pr_text = f"""Branch: {pr.branch_name}
Commit: {pr.commit_message}
Title: {pr.pr_title}

{pr.pr_body}"""
            st.code(pr_text)
            st.info("Copy the text above!")
    
    st.markdown("---")
    
    # Render the briefing
    st.markdown(agent3.briefing_markdown)
    
    # PR Draft section
    st.markdown("---")
    st.markdown("### 📝 PR Draft")
    
    pr = agent3.pr_draft
    st.code(f"git checkout -b {pr.branch_name}", language="bash")
    st.code(f'git commit -m "{pr.commit_message}"', language="bash")
    st.code(f"# PR Title: {pr.pr_title}", language="bash")
    
    with st.expander("Full PR Body"):
        st.markdown(pr.pr_body)
    
    # Test commands
    if agent3.test_commands:
        st.markdown("### 🧪 Test Commands")
        for cmd in agent3.test_commands:
            st.code(cmd, language="bash")
    
    # Risk notes
    if agent3.risk_notes:
        st.markdown("### ⚠️ Risk Notes")
        for note in agent3.risk_notes:
            st.warning(note)


def run_analysis(config: dict):
    """Run the analysis pipeline."""
    st.session_state.status_messages = []
    st.session_state.running = True
    
    status_container = st.empty()
    
    try:
        groq_client = GroqClient()
        github_client = GitHubClient()
        cache_manager = CacheManager()
        
        orchestrator = ScoutOrchestrator(
            github_client=github_client,
            groq_client=groq_client,
            cache_manager=cache_manager,
            fast_model=config["fast_model"],
            powerful_model=config["powerful_model"]
        )
        
        # Status callback
        def update_status(msg):
            st.session_state.status_messages.append(msg)
            with status_container:
                for m in st.session_state.status_messages[-5:]:
                    st.info(m)
        
        orchestrator.set_status_callback(update_status)
        
        # Run the pipeline
        results = orchestrator.run(
            repo_url=config["repo_url"],
            beginner_only=config["beginner_only"]
        )
        
        st.session_state.results = results
        
    except Exception as e:
        st.session_state.results = {
            "success": False,
            "error": str(e)
        }
    
    finally:
        st.session_state.running = False


def main():
    """Main application entry point."""
    init_session_state()
    render_header()
    
    # Sidebar returns action config
    action = render_sidebar()
    
    if action and action["action"] == "generate":
        run_analysis(action)
    
    # Main content area
    if st.session_state.results:
        results = st.session_state.results
        
        if not results.get("success"):
            st.error(f"❌ Error: {results.get('error', 'Unknown error')}")
        else:
            # Repository info
            repo = results.get("repo")
            if repo:
                st.markdown(f"""
                **Repository:** [{repo.full_name}]({repo.html_url}) | 
                **Language:** {repo.language or 'Unknown'} | 
                **Stars:** ⭐ {repo.stargazers_count} |
                **Open Issues:** 📋 {repo.open_issues_count}
                """)
                
                if results.get("duration_seconds"):
                    st.caption(f"Analysis completed in {results['duration_seconds']:.1f} seconds")
            
            # Tabs for different views
            tab1, tab2, tab3 = st.tabs([
                "🏆 Issue Ranking",
                "🔍 Code Locator",
                "📋 Contributor Briefing"
            ])
            
            with tab1:
                render_issue_ranking(results)
            
            with tab2:
                render_code_locator(results)
            
            with tab3:
                render_briefing_document(results)
    else:
        # Welcome message
        st.markdown("""
        ## Welcome to Open Source Scout! 🎉
        
        This tool helps you find and contribute to open-source projects by:
        
        1. **🔍 Finding beginner-friendly issues** - We analyze and rank issues based on clarity, activity, and complexity
        2. **📍 Locating relevant code** - We search the codebase to find exactly where to make changes
        3. **📝 Generating a contribution guide** - We create a detailed briefing document with fix plans and PR drafts
        
        ### Getting Started
        
        1. Enter a GitHub repository URL in the sidebar
        2. Choose your options (beginner mode, model selection)
        3. Click "Generate Analysis"
        4. Explore the results across the three tabs
        
        ### Try it now!
        
        Use one of the demo repos in the sidebar, or paste any public GitHub repository URL.
        """)


if __name__ == "__main__":
    main()
