# PlantLens

Visual plant health assistant: **photo → check for a problem → retrieve from a small knowledge base → provisional diagnosis**, with optional follow-up questions, a plant journal, saved chats and a weather-impact check.

## Open source
MIT licensed ([LICENSE](LICENSE)). The project is built on open-weight models:

| Role | Model | License |
|---|---|---|
| Main vision-language model | Qwen3-VL-30B-A3B / 8B-Instruct | Apache-2.0 |
| Plant-ID votes (other families) | Gemma, Llama | Gemma terms / Llama community license |
| KB embedder (local) | sentence-transformers/all-MiniLM-L6-v2 | Apache-2.0 |

Models are called through any OpenAI-compatible endpoint. To run fully local, serve a Qwen3-VL build with Ollama or vLLM and set `PLANTLENS_BASE_URL=http://localhost:11434/v1` and `PLANTLENS_MODEL=<local model name>`; no `HF_TOKEN` is needed for a localhost URL.

## Agent skill
[`plantlens/`](plantlens/) is an Agent Skill following the Agent Skills open standard: `SKILL.md` (YAML frontmatter `name` + `description`), `references/` and `evals/`. Install by copying the folder into `.claude/skills/` (or your agent's skills directory).

## Harness (original implementation)
The `src/` pipeline is an original model harness around open-weight models, not a thin API call:
- **Router** sends photos/diagnose requests, plain plant questions and off-topic messages down different paths.
- **Per-symptom photo verification:** every symptom the model reports is re-checked against the image.
- **Code-written output:** steps, sources and questions come from retrieved KB records, not model memory.
- **Multi-family identification vote** (Qwen x3 + Gemma + Llama) with calibrated confidence.
- **Citation guardrails:** numbers checked in code, wording by a second model call; web fallback restricted to trusted domains.
- **Tracing and context ledger** for every model call (`src/trace.py`, `src/limits.py`).
- Provider fallback across hosts, and CI-run offline tests (`.github/workflows/tests.yml`).

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
