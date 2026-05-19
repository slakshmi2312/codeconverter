# Code Converter

FastAPI + React application for converting source code between Python, Java, C, and JavaScript using a hybrid rule-based + LLM pipeline, with remote code execution via Judge0.

## Run Locally

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend

```powershell
cd frontend
npm install
copy .env.example .env
npm run dev
```

Frontend: `http://localhost:5173`  
Backend: `http://localhost:8000`
