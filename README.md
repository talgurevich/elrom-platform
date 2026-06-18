# elrom-platform

Kibbutz bylaws & decisions search — MVP.

See `mvp-spec.md` in the sibling `elrom/` directory for the product specification.

## Quickstart

### Prerequisites

- Python 3.11+
- Node 20+
- Docker (for local Postgres with pgvector)

### One-time setup

```bash
# Clone (if you haven't already)
git clone https://github.com/talgurevich/elrom-platform.git
cd elrom-platform

# Copy env template and fill in your API keys
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY, COHERE_API_KEY, OPENAI_API_KEY

# Install backend dependencies
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..

# Install frontend dependencies
cd frontend
npm install
cd ..
```

### Run it

```bash
# Start local Postgres + pgvector
make db-up

# Run migrations
make migrate

# Start the backend (in one terminal)
make backend

# Start the frontend (in another terminal)
make frontend
```

Backend: http://localhost:8000
Frontend: http://localhost:5173
API docs: http://localhost:8000/docs

### First smoke test

Once everything is up:

```bash
# Health check
curl http://localhost:8000/api/health

# Ingest a sample document
curl -X POST http://localhost:8000/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"filename": "test.txt", "text": "תקנון הקליטה של הקיבוץ. סעיף 1: כל חבר חדש..."}'

# Ask a question (in Hebrew)
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"question": "מה כתוב על קליטה של חבר חדש?"}'
```

## Project layout

```
elrom-platform/
├── backend/         # FastAPI + SQLAlchemy + Alembic + pgvector
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models.py        # SQLAlchemy schema (matches mvp-spec §3.3)
│   │   ├── routes/          # API endpoints
│   │   └── services/        # ingest, retrieval, embedding, llm
│   ├── alembic/             # database migrations
│   └── requirements.txt
├── frontend/        # React + Vite + Tailwind + shadcn/ui (RTL)
├── docker-compose.yml       # local Postgres+pgvector
├── Makefile                 # common commands
├── .env.example             # required environment variables
└── mvp-spec.md → ../elrom/mvp-spec.md   # the spec
```

## Status

Scaffold only. Real retrieval pipeline + UI come in Weeks 1–4 of the build plan in `mvp-spec.md`.
