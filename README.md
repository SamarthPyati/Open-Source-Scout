# Open Source Scout 🔭

An AI-powered multi-agent system that helps beginners contribute to open-source projects by automating the journey from **issue discovery → code location → fix planning → PR drafting**.

## 🌟 Features

- **Smart Issue Ranking**: Automatically finds and ranks beginner-friendly issues using a scoring algorithm
- **Code Location**: Searches the codebase to find exactly where changes are needed
- **Contributor Briefing**: Generates comprehensive fix plans with step-by-step instructions
- **PR Draft Generation**: Creates ready-to-use branch names, commit messages, and PR descriptions
- **Export Options**: Download briefings as Markdown or PDF

## 🚀 Quick Start

### Prerequisites

- Python 3.11 or higher
- Git
- (Optional) [ripgrep](https://github.com/BurntSushi/ripgrep) for faster code search

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/SamarthPyati/Open-Source-Scout.git
   cd Open-Source-Scout
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   
   # Windows
   venv\Scripts\activate
   
   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   # Copy the example file
   cp .env.example .env
   
   # Edit .env and add your API keys
   # GROQ_API_KEY=your_groq_key
   # GITHUB_TOKEN=your_github_token (optional but recommended)
   ```

### Running the App

```bash
streamlit run app/main.py
```

The app will open in your browser at `http://localhost:8501`

## 📖 How to Use

1. **Enter a Repository URL**: Paste any public GitHub repository URL
2. **Choose Options**:
   - **Beginner-only mode** (default): Filters for `good first issue`, `help wanted`, etc.
   - **Any issue mode**: Analyzes all open issues
3. **Click Generate**: The 3-agent pipeline will analyze the repo
4. **Explore Results**:
   - **Issue Ranking Tab**: See top 3 issues with score breakdowns
   - **Code Locator Tab**: Find relevant files and functions
   - **Contributor Briefing Tab**: Get the full fix plan and PR draft
5. **Export**: Download as Markdown or PDF

## 🎯 Demo Examples

Try these repositories to see Open Source Scout in action:

### Example 1: FastAPI
```
https://github.com/tiangolo/fastapi
```
A popular Python web framework with well-maintained beginner issues.

### Example 2: httpx
```
https://github.com/encode/httpx
```
A modern HTTP client with good documentation and clear issues.

## 🏗️ Architecture

### Multi-Agent Pipeline

| Agent | Role | Model |
|-------|------|-------|
| **Triage Nurse** | Fetches and ranks issues by beginner-friendliness | qwen-qwq-32b |
| **Archaeologist** | Searches codebase, identifies files/functions | qwen-qwq-32b |
| **Senior Dev** | Creates fix plan, tests, and PR draft | llama-3.3-70b |

### Scoring Algorithm (0-100)

| Component | Max Points | Description |
|-----------|------------|-------------|
| Labels | 25 | `good first issue`, `help wanted`, etc. |
| Clarity | 20 | Description quality, formatting, examples |
| Activity | 15 | Recent updates, comment activity |
| Size Estimate | 20 | Estimated effort level |
| Risk Penalty | -20 | Complexity, breaking changes, security |

## 📁 Project Structure

```
Open-Source-Scout/
├── app/
│   └── main.py              # Streamlit UI
├── core/
│   ├── agents/
│   │   ├── triage_nurse.py  # Issue ranking
│   │   ├── archaeologist.py # Code location
│   │   └── senior_dev.py    # Fix planning
│   ├── scoring.py           # Scoring algorithm
│   ├── orchestrator.py      # Pipeline coordination
│   └── schemas.py           # Pydantic models
├── integrations/
│   ├── github_client.py     # GitHub API
│   └── groq_client.py       # Groq LLM API
├── utils/
│   ├── cache.py             # Caching
│   ├── code_search.py       # ripgrep/Python search
│   ├── pdf_generator.py     # PDF export
│   └── text_chunking.py     # Token management
├── tests/
│   ├── test_scoring.py      # Scoring tests
│   └── test_schemas.py      # Schema tests
├── .cache/                   # Runtime cache (gitignored)
├── .env                      # API keys (gitignored)
├── .env.example              # Template
└── requirements.txt          # Dependencies
```

## 🔧 Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | Groq API key for LLM access |
| `GITHUB_TOKEN` | No | GitHub token for higher rate limits (5000 vs 60 req/hr) |

### Model Selection

The app offers three model configurations:
- **Recommended** (default): Balanced speed and quality
- **Fast**: Prioritizes speed for quick analysis
- **Balanced**: Uses powerful model for all agents

## 🧪 Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_scoring.py -v
```

## ⚠️ Important Notes

- **No Auto-Commits**: This tool generates guidance only—it never modifies upstream repos
- **Public Repos Only**: Works with any public GitHub repository
- **Rate Limits**: Without a GitHub token, you're limited to 60 requests/hour
- **Large Repos**: Uses efficient code search to handle large codebases

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).

## 🤝 Contributing

Contributions are welcome! Feel free to:
- Open issues for bugs or feature requests
- Submit pull requests
- Share feedback on the scoring algorithm

---

Built with ❤️ using Streamlit, Groq, and the GitHub API.