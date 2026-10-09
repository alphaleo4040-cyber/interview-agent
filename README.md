# AI Job Interview Chatbot (OpenAI Agents SDK + Groq + Django)

An intelligent, multi-agent AI job interviewer chatbot built with the **OpenAI Agents SDK** (`openai-agents`) powered by fast open-weights LLMs via the **Groq API** (`openai/gpt-oss-120b`, `qwen/qwen3.8-27b`), featuring a clean **Django web interface** with user authentication, resume parsing, and tailored job description alignment.

---

## Features

- **OpenAI Agents SDK Framework**: Multi-agent orchestration using OpenAI's official `openai-agents` package with Groq OpenAI-compatible model endpoints.
- **Ultra-Fast LLM Inference**: Powered by Groq (`openai/gpt-oss-120b`).
- **Multi-Agent Orchestration**:
  - **`InterviewerAgent`**: Asks targeted, grounded technical and behavioral questions one-by-one.
  - **`EvaluatorAgent`**: Performs holistic assessment, generating structured hiring reports with scores, strengths, and recommendations.
- **Resume Upload & Parsing**: Automatically extracts experience and skills from `.pdf`, `.docx`, and `.txt` files.
- **Job Description Targeting**: Select from 5 built-in technical role templates or paste custom requirements.
- **Standard Django Architecture**: Clean, modular Django structure with authentication, sessions, and management commands.
- **Dual Interfaces**: Full-featured single-page Web application + interactive Terminal CLI.

---

## Project Structure

```text
resume agent/
├── manage.py                          # Django management script
├── requirements.txt                  # Python dependencies (openai-agents, django, pypdf, etc.)
├── db.sqlite3                        # SQLite database
├── .env                              # Environment configuration (GROQ_API_KEY)
├── .env.example                      # Example configuration
├── main.py                           # Standalone CLI entrypoint
│
├── web_interview/                    # Django project configuration
│   ├── __init__.py
│   ├── settings.py                   # Django settings
│   ├── urls.py                       # Root URL routing
│   ├── wsgi.py
│   └── asgi.py
│
└── interview_app/                    # Core Django application
    ├── __init__.py
    ├── admin.py
    ├── apps.py
    ├── config.py                     # Groq client & model initialization
    ├── forms.py                      # Registration & login forms
    ├── interview_agents.py           # Interviewer & Evaluator agent logic
    ├── models.py                     # Data models
    ├── resume_parser.py              # PDF/DOCX/TXT parser & JD templates
    ├── session.py                    # In-memory agent conversation store
    ├── tests.py                      # Django test suite
    ├── tools.py                      # Scoring tools & session state
    ├── urls.py                       # Application endpoints
    ├── views.py                      # Web views & JSON APIs
    │
    ├── management/                   # Custom Django commands
    │   └── commands/
    │       └── cli_interview.py      # python manage.py cli_interview
    │
    └── templates/                    # App templates
        └── interview_app/
            ├── index.html            # Main interview dashboard
            ├── login.html            # User login page
            └── register.html         # User registration page
```

---

## Setup & Running

### 1. Configure your Groq API Key
Obtain a free key from the [Groq Console](https://console.groq.com).
Edit `.env` in the project root:

```env
GROQ_API_KEY=gsk_your_actual_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b
OPENAI_AGENTS_DISABLE_TRACING=1
```

### 2. Install Dependencies
```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
```

### 3. Run the Web Interface (Django)
```powershell
.\.venv\Scripts\python manage.py runserver
```
Navigate to **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)** in your browser. Register an account or sign in to start the interview simulator.

### 4. Run the Terminal CLI
You can run the terminal interface in either of two ways:
```powershell
# Via Django management command:
.\.venv\Scripts\python manage.py cli_interview

# Or via direct CLI script:
.\.venv\Scripts\python main.py
```

### 5. Run the Automated Tests
```powershell
.\.venv\Scripts\python manage.py test
```
