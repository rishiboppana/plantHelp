# PlantLens KB — Hand-off for Claude Code

Batch 1 of the knowledge base is drafted and passes validation. Your job now has two parts. Work one part at a time and report after each.

## What exists

```
kb/
  vocab/        symptoms, plant_parts, cause_categories, location_patterns, plants (10 target plants + groups)
  sources/      sources.yaml  (6 sources; license: unknown; policy: short paraphrased facts + URL only)
  schema/       record.schema.json
  records/draft/records_batch1.json   (57 records, all status: draft)
  review/review_batch1.csv            (sheet the human fills in: approve / edit / reject)
tools/build_batch1.py                 (generator; use as the template for batch 2)
src/validate/validate.py              (run after every change: python src/validate/validate.py)
```

Batch 1 coverage: generic houseplant problems (pests, diseases, symptom-to-cause tables), jade, pothos, snake plant, light profiles for 7 plants.

## Hard rules (same as the plan)

- Records come from the source pages only. Extract, in your own words. No outside knowledge. Empty field when the page is silent.
- Items not literally stated but implied by a stated cause must be tagged `basis: "derived_from_cause"`.
- Mark `unsure: true` when a page is thin or ambiguous.
- Never write to `status: reviewed` yourself. Only the human review step does that. Never index `draft` records into the final search index used by the app, except in clearly marked test runs.
- Do not copy passages. Keep the source URL on every record.
- If a page will not load, skip it and report it. Do not fill from memory.

## Part A — Build the search (graph + prefilter)

Build the `search_plant_kb(observation) -> {records, coverage, filters_applied, filters_relaxed}` function that `plantlens/SKILL.md` expects. Observation object schema is in `SKILL.md`.

1. **Storage:** SQLite. Tables: `records`, an FTS5 table over (cause + summary + symptom labels and synonyms + plant names and aliases), and graph tables.
2. **Graph (lightweight, in SQLite, no graph DB):** nodes = Plant, PlantGroup, Symptom, Cause (record), Question, Action. Edges: Plant -belongs_to-> Group; Symptom -indicates-> Cause record; Cause record -asks-> Question; Cause record -suggests-> Action.
3. **Prefilter (graph walk), applied before any scoring:**
   - Plant known (confidence not low): records whose `plants` contains it, plus records whose `plant_groups` contains one of the plant's groups.
   - Plant unknown: no plant filter.
   - Symptoms: require overlap with the observation's symptom ids. Records with `symptoms_stated: false` are not dropped by this rule; they stay reachable through plant/group match and keyword search.
   - `plant_profile` records are fetched separately by plant, to describe what normal looks like. They are not causes.
4. **Rank inside the filtered set:** BM25 (FTS5) over the observation's symptom terms and plant names. Add vector search only if the retrieval test shows keyword misses. Prefer plant-specific records over generic ones when both match.
5. **Cut to K=5.** If fewer than 3 survive, relax in this order and report it in `filters_relaxed`: drop `plant_parts`, then plant (keep group), then symptom overlap.
6. **Coverage:** `good` = at least 2 problem records matched with a plant-specific or strong symptom match; `weak` = only generic or only 1 weak match; `none` = nothing relevant. Put the thresholds in a config file.
7. **Follow-up questions:** from the top records, collect `distinguishing_questions`. Prefer questions that appear on one candidate cause but not the others. Return 2–4. Prefer `basis: page` questions when available.
8. **Return** the fields the skill needs: cause, category, summary, questions, actions, inspect items, source id and URL, record id.

Acceptance:
- Index builds from `records/draft` with a `--include-drafts` flag (clearly labeled for testing) and from `records/reviewed` by default.
- Test with these observations and report the output of each:
  - Calathea photo: `dry_brown_patch` plus `brown_tips_edges`, plant `unknown` (expect `weak` coverage from generic records, with an honest note).
  - Jade: `leaf_drop`, plant `jade` (expect the jade record first).
  - Healthy snake plant: should return the plant profile and no causes.
  - Something not covered (e.g., `holes_chewed`): expect `none` or `weak`.

## Part B — Batch 2 records (after the human approves batch 1)

Remaining target plants: **peace lily, spider plant, aloe vera, Chinese evergreen, monstera, African violet, dracaena.**

1. Find plant-specific university extension pages for each (prefer pages on `.edu` extension sites). Read each page and extract facts the same way batch 1 did. Add data to `tools/build_batch1.py` (copy it to `build_batch2.py` so batch 1 stays frozen), using the same `rec()` / `abiotic()` helpers.
2. Candidate pages already seen but not read: UF/IFAS Dracaena fact sheet (FPS183 at https://ask.ifas.ufl.edu/publication/FP183/pdf; it says little about problems), the University of Nebraska houseplants page (https://byf.unl.edu/houseplants; generic), and plant pages on Oklahoma State, NC State, and Wisconsin extension sites. Check each page's content before relying on it.
3. Calathea: no university problem source was found. Do not add commercial blog content for it without asking the human.
4. Add each new source to `sources.yaml` with `license` as found (or "unknown") and a policy note. Run the validator.
5. Regenerate `review_batch2.csv` for the human.

## Report back after each part

- What was built, counts, validator result.
- Anything skipped or unsure, and why.
- For Part A: the four test outputs above.
