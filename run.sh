#!/bin/sh
# Starts API (:8000) and UI (:5173). Needs HF_TOKEN in .env (repo root or src/); the model runs on the Hugging Face router by default; a local OpenAI-compatible server also works (see README).
cd "$(dirname "$0")"
(cd backend && .venv/bin/uvicorn main:app --port 8000 --reload) &
(cd frontend && npm run dev) &
wait
