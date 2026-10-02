# PlantLens — Colab Test Plan (Features 1–4 only)

> Audience: Claude Code. You write the notebook and helper code; the human runs it in Google Colab and brings results back. Work one phase at a time. After each phase, stop and report before starting the next.

## Goal

Find out, quickly, whether a Qwen vision model following the `plantlens` skill can do features 1–4 well enough to build on:

1. Visual plant check (describe visible symptoms, identify the plant, judge healthy or not)
2. Smart follow-up questions
3. Likely problem possibilities (2–4, never one diagnosis)
4. Next-action checklist

**Out of scope:** the real knowledge base, retrieval, fine-tuning, UI, plant history, symptom map, and every feature numbered 5 or higher. Do not build any of these.

## Inputs

- `plantlens/` skill folder: `SKILL.md`, `references/symptoms.md`, `references/examples.md`, `evals/evals.json`. Do not edit `SKILL.md` unless a phase says so. If you think it needs a change, report the change and the evidence; do not apply it silently.
- Test photos in `test_photos/` (the human will provide ~20: some healthy, some with visible problems, at least one blurry, at least one with an unusual symptom). If the folder is empty, stop and ask.
- A Hugging Face token, stored in Colab Secrets as `HF_TOKEN`. Never write a token into the notebook or any output file.

## Fixed decisions

- Model: a Qwen3-VL instruct model. **Look up the exact model id on the Hugging Face hub before using it; do not guess ids.** Size depends on the Colab GPU: check `nvidia-smi` first. On a ~16 GB GPU use a smaller size or a 4-bit/8-bit quantized load; record which one you used.
- No real knowledge base. Use a **stub** `search_plant_kb` backed by a few hand-written test fixtures (see Phase 2). The fixtures are for testing behavior only and are never presented as real plant knowledge.
- Keep the harness minimal and shaped like the final one: observation call, then reply call. See Phase 2.

## Phase 0 — Environment and model smoke test

**Do**
1. Notebook cell: check GPU (`nvidia-smi`), install dependencies, read `HF_TOKEN` from Colab Secrets.
2. Load the chosen model. If load fails or runs out of memory, step down to a smaller size or stronger quantization and record why.
3. Mount Google Drive and cache the model weights there so a runtime reset does not mean a full re-download.
4. Send one photo plus the prompt "Describe what you see." Print the result and the time taken.

**Report back:** GPU, model id and size, quantization, load time, memory used, time per response, and whether the output looks sensible.

**Stop if:** the model cannot load or answer an image prompt. Then try the fallback: the Hugging Face router at `https://router.huggingface.co/v1` (OpenAI-compatible), after checking which provider serves a vision model. Report which route works.

## Phase 1 — Skill wiring

**Do**
1. Build the system prompt from `SKILL.md` + `references/symptoms.md`. Keep `examples.md` out at first; add it only if outputs are badly off (and report that you did).
2. Write `run_case(photo, user_text, history)` that sends image + text and returns the reply.
3. Run on 3 photos (one healthy, one with a clear problem, one blurry). Print the full replies.

**Report back:** whether the replies follow the format (What I see → Plant → Overall → Questions → …), whether they stop after Questions when the plant is unconfirmed, and any rule the model clearly ignored.

## Phase 2 — Observation call and stub knowledge base

**Do**
1. **Observation call:** ask the model to output only the observation JSON (schema in `SKILL.md`). Use constrained or JSON-mode output if the runtime supports it; otherwise parse and retry once on invalid JSON. Validate that every symptom id exists in `references/symptoms.md`.
2. **Stub knowledge base:** create `fixtures/test_records.json` with 6–8 clearly labeled placeholder records (symptom, cause, category, one distinguishing question, next actions). Mark each `"fixture": true`. Add a matching `search_plant_kb(observation)` that returns records by simple symptom overlap and a `coverage` value (`good | weak | none`). Include at least one case that returns `none`.
3. **Reply call:** give the model the observation plus the returned records and ask for the reply in the skill's format.
4. **Multi-turn:** support appending a user answer (for example "it's a tomato, lower leaves first, soil stays wet") and re-running.

**Report back:** JSON validity rate across your test photos, and whether each reply used only fixture records.

## Phase 3 — Run the test set and score

**Do**
1. Run all 7 cases in `evals/evals.json`, plus every photo in `test_photos/` at least once, plus one multi-turn run.
2. Save every transcript to `results/transcripts/<case>.md`.
3. Write `results/scores.csv` with one row per case. Mark each check pass/fail. Automatic checks should be code; judgment checks are left blank for the human to fill in.

**Automatic checks (code)**
- Observation JSON is valid and uses only known symptom ids.
- Number of follow-up questions is 2–4.
- Number of possible causes is 2–4 when `coverage` is `good`, and 0 when `none`.
- Checklist has 3–6 items and includes a re-check window.
- Every cause shown maps to a fixture record id (no outside causes).
- No pesticide product names or doses appear.
- A blurry photo produces a request for a better photo, not a diagnosis.
- Off-topic prompts are declined.

**Human-judged checks (leave blank)**
- Feature 1: are the described symptoms actually visible in the photo? Is the plant identification right? Is "healthy vs problem" right?
- Feature 2: are the questions useful, or generic?
- Feature 3: do the possibilities fit what is visible?
- Feature 4: are the steps practical and gentle?
- Uncertainty: does it say "not sure" when it should, and avoid naming a disease from a photo?

**Report back:** `scores.csv`, a short summary of pass rates per feature, and the 3 worst transcripts.

## Phase 4 — Decide

Using the results, write `results/DECISION.md` with a recommendation for each failure pattern. Use this logic:

| Failure | Likely fix |
|---|---|
| Wrong format, extra sections, ignores the stop-and-ask rule | Tighten `SKILL.md` wording, add an example |
| Invalid JSON or unknown symptom ids | Constrained output, or retry logic in the harness |
| Describes things not in the photo | Stronger "observe first" wording; try a larger model |
| Confident wrong plant identification | Ask the user more often; consider a dedicated plant ID model later |
| Invents causes outside the records | Move the check into code (reject replies with unknown record ids) |
| Slow or unreliable on Colab | Switch to the Hugging Face router, or a smaller model |
| Weak visual detail even after prompt fixes | Try a larger model before considering fine-tuning |

Fine-tuning is not an option at this stage.

## Guardrails

- Never put `HF_TOKEN` or any secret in the notebook, outputs, or logs.
- Do not invent plant facts. Fixtures are labeled placeholders only.
- Do not change `SKILL.md` without reporting the change and why.
- Cache model weights to Drive; do not re-download on every run.
- Keep all settings (model id, quantization, max tokens, temperature) in one config cell.
- Stop and ask the human when blocked (no photos, no GPU, token missing).

## Time box

About 60 minutes total: Phase 0 (10–15), Phase 1 (10), Phase 2 (15–20), Phase 3 (15), Phase 4 (5). If Phase 0 runs past 25 minutes, switch to the Hugging Face router and report.

## Deliverables

- `plantlens_colab_test.ipynb`
- `fixtures/test_records.json`
- `results/transcripts/`, `results/scores.csv`, `results/DECISION.md`
