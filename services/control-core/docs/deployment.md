# Deployment Guide

## Prerequisites

- **Python 3.11+** (required)
- **Node.js 18+** (optional, for frontend development only)
- **Docker 20.10+** (optional, for containerized deployment)
- **Git** (optional)

## Quick Start

### 1. Install

```bash
# Clone the repository
git clone <repo-url> myself-agent
cd myself-agent

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install with dev dependencies
pip install -e ".[dev]"

# Optional: install browser tools (requires Playwright)
pip install -e ".[browser]"

# Optional: install docx tools
pip install -e ".[docx]"
```

### 2. Configure

#### Environment Variables

Create a `.env` file in the project root:

```bash
# Database (default: sqlite:///./data/agent_platform.db)
DATABASE_URL=sqlite:///./data/agent_platform.db

# LLM Provider: mock (default), deepseek
LLM_PROVIDER=mock

# Secret key for capability token signing (CHANGE IN PRODUCTION)
SECRET_KEY=your-secret-key-here

# DeepSeek API key (required if LLM_PROVIDER=deepseek)
DEEPSEEK_API_KEY=your-api-key

# Logging
LOG_LEVEL=INFO
JSON_LOGS=false
```

#### Configuration Files

All configuration files are in the `configs/` directory:

| File | Purpose |
|------|---------|
| `configs/app.yaml` | Application settings |
| `configs/tools.yaml` | Tool definitions with risk levels and schemas |
| `configs/policy.yaml` | Policy rules and forbidden patterns |
| `configs/memory.yaml` | Memory retrieval settings |
| `configs/skills.yaml` | Skill degradation thresholds |
| `configs/models.yaml` | LLM model configuration |
| `configs/editions/enterprise.yaml` | Enterprise edition profile |
| `configs/editions/personal.yaml` | Personal edition profile |

The default configuration works out of the box for development with the mock LLM provider.

### 3. Initialize Database

```bash
python scripts/init_db.py
```

This creates the `data/` directory and all 8 database tables.

### 4. Run the API Server

```bash
python scripts/run_api.py
```

The server starts at `http://0.0.0.0:8000` with hot-reload enabled.

Verify it is running:

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"1.0.0","edition":"enterprise"}
```

### 5. Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=packages --cov=apps

# Run specific test categories
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only
pytest -m security      # Security tests only
pytest -m e2e           # End-to-end tests only
```

## Docker Deployment

### Build and Run

```bash
# Build the image
docker compose build

# Start the service
docker compose up -d

# View logs
docker compose logs -f api

# Stop the service
docker compose down
```

### Docker Configuration

The `docker-compose.yml` mounts two volumes:

- `./data:/app/data` — SQLite database persistence
- `./workspace:/app/workspace` — Workspace directory for file tool operations

Environment variables are loaded from `.env`. Override defaults in `docker-compose.yml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/agent_platform.db` | Database connection string |
| `LLM_PROVIDER` | `mock` | LLM provider selection |
| `SECRET_KEY` | `change-me-in-production` | HMAC signing key for capability tokens |

### Health Check

The Docker container includes a health check that hits `/health` every 30 seconds. The service reports as healthy once it responds with `{"status": "ok"}`.

### Multi-stage Docker Build

The Dockerfile uses a two-stage build:

1. **Builder stage**: Installs dependencies with build tools
2. **Runtime stage**: Copies installed packages only, runs as non-root user (`appuser`)

## Frontend Development

The enterprise admin web application lives in `apps/enterprise_admin_web/`.

```bash
cd apps/enterprise_admin_web

# Install dependencies
npm install

# Start dev server (http://localhost:3000)
npm run dev

# Build for production
npm run build
```

The frontend dev server proxies `/api` requests to the backend at `http://localhost:8000`.

### Admin Web Pages

| Page | Route | Description |
|------|-------|-------------|
| Dashboard | `/` | Stats cards, recent tasks, pending approvals |
| Task List | `/tasks` | Filterable task table with create/cancel |
| Task Detail | `/tasks/:id` | Steps, results, audit timeline |
| Audit Log | `/audit` | Filterable event log |
| Memory List | `/memory` | Search, filter, disable/delete |
| Skill List | `/skills` | Status management, approve/disable/rollback |
| Approvals | `/approvals` | Resolve pending approval requests |

## WebSocket Support

Real-time task progress updates via WebSocket:

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/tasks/{task_id}");

ws.onmessage = (event) => {
  const update = JSON.parse(event.data);
  console.log("Task update:", update);
};

// Keep alive
setInterval(() => ws.send("ping"), 30000);
```

## Running with a Real LLM

To use DeepSeek instead of the mock provider:

### 1. Set Environment Variables

```bash
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-key-here
```

### 2. Configure Model Settings

Edit `configs/models.yaml`:

```yaml
providers:
  deepseek:
    base_url: "https://api.deepseek.com/v1"
    model: "deepseek-chat"
    temperature: 0.3
    max_tokens: 4096
```

### 3. Restart the Server

```bash
python scripts/run_api.py
```

## Production Checklist

- [ ] Set `SECRET_KEY` to a strong random value (`python -c "import secrets; print(secrets.token_hex(32))"`)
- [ ] Set `JSON_LOGS=true` for structured logging
- [ ] Restrict CORS origins (replace `allow_origins=["*"]` with specific domains)
- [ ] Configure `LLM_PROVIDER=deepseek` with valid API key
- [ ] Set up reverse proxy (nginx/caddy) for TLS termination
- [ ] Review rate limit settings (default: 60 req/min per IP)
- [ ] Set up database backups
- [ ] Use PostgreSQL for production workloads (`DATABASE_URL=postgresql://...`)
- [ ] Increase uvicorn workers (`--workers 4`)

## Project Structure

```
myself-agent/
  apps/
    api_server/            # FastAPI application
      main.py              # App entry point, middleware, routers
      dependencies.py      # Shared dependencies (DB session, pagination)
      routes/              # 10 route modules
        tasks.py           # Task CRUD + lifecycle
        memory.py          # Memory search/management
        skills.py          # Skill lifecycle
        audit.py           # Audit event queries
        approvals.py       # Approval workflow
        personal.py        # Personal edition APIs
        editions.py        # Edition configuration
        chat.py            # Conversational interface
        voice.py           # STT/TTS/voice commands
        ws.py              # WebSocket real-time updates
    enterprise_admin_web/  # Vue 3 + Element Plus admin interface
  packages/
    agent_core/            # Task system, orchestrator, state machine, edition manager
    db/                    # SQLAlchemy models, session, repositories
    executor/              # Executor service, tool runner, tool implementations
    llm_gateway/           # LLM provider routing (mock, deepseek)
    memory/                # Memory service, retriever, summarizer, scorer
    planner/               # Planner service, plan validator, prompt templates
    policy/                # Policy engine, capability token, tool registry
    skills/                # Skill service, extractor, registry, evaluator
    voice/                 # Speech-to-text, text-to-speech, command routing
    vision/                # OCR service, screen capture, image OCR
    evaluation/            # Task evaluator, quality metrics
    observability/         # Structured logging, JSON formatter
    middleware/            # Rate limiting middleware
    personal_context/      # Personal context and reminder services
  configs/                 # YAML configuration files
  scripts/                 # init_db.py, run_api.py, demos
  tests/                   # 516 tests (unit, integration, security, e2e)
  docs/                    # Documentation
  pyproject.toml           # Project metadata and dependencies
  Dockerfile               # Multi-stage Docker build
  docker-compose.yml       # Docker Compose service definition
```
