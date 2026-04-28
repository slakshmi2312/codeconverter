# Multi-Language Code Converter (Hybrid)

This project contains:

- `backend/` - FastAPI + OpenAI
- `frontend/` - React + Vite + Tailwind + Monaco Editor

The backend runs on port `8000` and exposes `POST /convert`.

## Backend setup (FastAPI)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Set key in `backend/.env`:

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini
```

Run backend:

```bash
uvicorn main:app --reload --port 8000
```

## Frontend setup (React)

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

Frontend URL: `http://localhost:5173`  
Backend URL: `http://localhost:8000`

## API contract

`POST /convert`

```json
{
  "code": "for i in range(3):\n    print(i)",
  "source_lang": "python",
  "target_lang": "java"
}
```

Response:

```json
{
  "converted_code": "...",
  "provider": "openai",
  "mode": "hybrid"
}
```

## Quality upgrades included

- AST validation pre/post conversion via `tree-sitter` + `tree-sitter-languages`
- Retry/fallback model strategy across multiple OpenAI models with per-model retries
- Golden test suite in `backend/tests/golden` + pytest checks in `backend/tests/test_transpiler_quality.py`
