# PlantLens

Visual plant health assistant: **photo → check for a problem → retrieve from a small knowledge base → provisional diagnosis**, with optional follow-up questions, a plant journal, saved chats and a weather-impact check.

## Run
1. Put a Hugging Face token (with "Make calls to Inference Providers") in `.env` at the repo root or in `src/`: `HF_TOKEN=hf_...` (git-ignored).
2. Backend (Python 3.12 venv in `backend/.venv`): `pip install -r backend/requirements.txt`, then `./run.sh` (API on :8000, UI on :5173).
   The model runs on the Hugging Face router (`src/remote_vlm.py`, with provider fallback); the knowledge base and its index run locally.
3. First start builds `kb/index/kb.sqlite` from `kb/records/reviewed/` with the embedder in `kb/config.yaml`.

## How a message is handled (`src/pipeline.py`)
- **Router:** a photo, `/diagnose`, the 🩺 button, or "what's wrong" runs the diagnosis; any other plant question gets a short plain answer; off-topic is declined.
- **Diagnosis:** the model reads the photo → each reported symptom is verified against the photo → local KB search (only if there is a problem) → the model writes the observation and 2-4 possible causes → the *code* appends next steps, sources and optional questions taken from the retrieved records.
- Replies show one summary line; tap it for the full reasoning.

## Honest answers
- **Plant identification** (`src/identify.py`): three independent looks from the main model plus one vote each from two other model families (Gemma, Llama). `high` only when every family agrees on a clear single subject; `medium` when a majority agree ("looks like X, could also be Y, please confirm"); `low` otherwise ("could not tell which plant this is", no invented names). A plant the user names is trusted. Alternatives that nobody agrees on are never shown.
- **Uncertainty mode:** when the likely causes span several categories, or the plant is not confirmed, the reply says so and names the one extra piece of evidence that would help most.
- **Reference-backed answers:** diagnosis steps and sources are written by code from the retrieved records. Care and safety questions are never answered from the model's memory: they must cite a knowledge-base record whose text actually supports the answer (numbers are checked in code, wording by a second model call), otherwise the app searches the web (trusted domains first, social and video sites dropped) and answers only from those results, with links. If nothing can be confirmed it says so.

## Knowledge base (`kb/`)
Vocabulary in `kb/vocab/` (the skill's `plantlens/references/symptoms.md` is generated from it: `python -m src.gen_skill_vocab`). Records are short paraphrased facts with a source URL; only `kb/records/reviewed/` is indexed. Validate with `python -m src.validate.validate`.

## Tests
`python -m unittest tests.test_pipeline tests.test_retrieve` (offline), `python -m src.eval_retrieval --misses` (retrieval metrics; results log in `kb/eval/RESULTS.md`).

## Known gaps
`/api/compare`, `/api/plan`, `/api/live` are placeholders. Care answers outside a diagnosis come from the model, not the KB. The KB covers 29 generic houseplant problems from three extension sources whose licenses are not open (short paraphrases + URLs only).
