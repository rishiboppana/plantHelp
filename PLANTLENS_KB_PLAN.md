# PlantLens Knowledge Base — Build Plan

> Audience: Claude Code (and the human owner). Follow phases in order. Each phase has deliverables and acceptance checks. Do not skip a check. Do not start a phase until the previous one passes.

## 0. Context and fixed decisions

PlantLens is a plant-problem assistant. A user uploads a photo; a vision-language model (VLM) describes what is visible; the system retrieves grounded knowledge; the model asks focused follow-up questions, lists 2–4 possible causes (never one absolute diagnosis), and gives a short next-action checklist.

**Already decided (do not revisit):**
- One local model handles both vision and reasoning/tool calling (candidate: Qwen3-VL family; final model and size are chosen separately by the owner). Design must still allow splitting into a VLM + reasoning model later by keeping the observation schema strict.
- Retrieval runs in **code**, not as a model decision. The pipeline always runs search and passes results to the model.
- The model must answer **only from retrieved records**. If records do not cover the case, it says so and asks questions.
- If the model is not confident about the plant, it asks the user.
- Retrieval is **hybrid**: metadata pre-filter → keyword (BM25) + vector search → rank fusion → small top-k. Goal: fewer, higher-quality results.
- Knowledge is stored as **structured records** (symptom → cause → question → action), plus a lightweight relationship graph. Not full Microsoft-style GraphRAG.
- A fine-tuned embedding model is **deferred**. Only consider it if Phase 6 shows vocabulary-mismatch misses.

**Open decisions (owner must answer; mark as TODO until answered):**
1. Scope: which plants (houseplants / vegetables / both), how many, which region.
2. Source list and license status for each source.
3. Hardware / runtime (affects embedding model size and vector store choice).
4. Fully offline, or is an internet connection acceptable at build time only (assumed: build-time only).

If an open decision blocks a step, stop and ask the owner. Do not guess scope or sources.

## 1. Principles

- **Quality over volume.** A smaller, correct, traceable corpus beats a large noisy one.
- **Provenance on everything.** Every record carries `source_id` and `source_url`. No record without a source.
- **No invented facts.** When drafting records from source text, extract; do not add knowledge from memory. If a field is not stated in the source, leave it null.
- **Shared vocabulary.** The VLM observation schema, the records, and the filters all use the same controlled symptom vocabulary (Phase 2).
- **Measure before optimizing.** Build the retrieval test set before tuning anything.
- **Licenses.** Check each source's license before storing its text. Store short extracted facts plus a URL where full text cannot be redistributed.

## 2. Repository layout

```
plantlens/
├── SKILL.md                      # behavior skill (separate task; references the KB via a search tool)
├── kb/
│   ├── vocab/
│   │   ├── symptoms.yaml         # controlled symptom vocabulary + synonyms
│   │   ├── plant_parts.yaml      # leaf, stem, fruit, flower, whole_plant, root, soil
│   │   ├── cause_categories.yaml # watering, nutrient, pest, disease, environment
│   │   └── plants.yaml           # plant ids, common names, scientific names, aliases, groups
│   ├── sources/
│   │   ├── sources.yaml          # source_id, title, url, publisher, license, date_accessed
│   │   └── raw/                  # downloaded/saved source text (only if license allows)
│   ├── records/
│   │   ├── draft/                # LLM-drafted records, unreviewed
│   │   └── reviewed/             # human-reviewed records (only these get indexed)
│   ├── schema/
│   │   └── record.schema.json    # JSON Schema for a record
│   ├── index/                    # built artifacts (git-ignored)
│   │   ├── kb.sqlite             # records + FTS5 + edges
│   │   └── vectors/              # vector index
│   └── eval/
│       ├── retrieval_set.jsonl   # query -> expected record ids
│       └── image_set/            # photos + expected observation (separate task)
├── src/
│   ├── ingest/                   # source -> draft records
│   ├── validate/                 # schema + vocabulary + provenance checks
│   ├── build_index.py            # reviewed records -> sqlite + vectors
│   ├── retrieve.py               # the hybrid retrieval function
│   └── eval_retrieval.py         # recall@k, MRR, per-query report
└── PLANTLENS_KB_PLAN.md          # this file
```

Adjust paths if the owner's repo differs, but keep the separation: vocab, sources, records (draft vs reviewed), index (built), eval.

## 3. Phases

### Phase 1 — Scope and sources
**Do**
- Get answers to open decisions 1–4 from the owner.
- Create `kb/sources/sources.yaml`. For each source: `source_id`, `title`, `publisher`, `url`, `license`, `date_accessed`, `redistributable` (true/false/unknown).
- Prefer: university extension guides, IPM pages, government agricultural publications, owner-provided notes.

**Deliverables**
- `sources.yaml` with every source listed and its license status.
- Initial scope: target plant list and the 10–15 most common problems for those plants.

**Accept when**
- Every source has a license note. Sources with `redistributable: unknown` are flagged for the owner and are not ingested yet.

### Phase 2 — Controlled vocabularies and schema
**Do**
- Write `kb/vocab/symptoms.yaml`: each symptom has an `id`, `label`, `synonyms` (lay terms and technical terms, e.g. "pale leaves", "chlorosis"), and optional `location_patterns` (lower leaves first, new growth, leaf edges, between veins, one side, whole plant).
- Write `plant_parts.yaml`, `cause_categories.yaml` (watering, nutrient, pest, disease, environment), and `plants.yaml` (id, names, aliases, `group` such as `solanaceae`, `succulent`, `leafy_green`, for cases where the plant is unknown or generalizing).
- Write `kb/schema/record.schema.json` for the record format below.

**Record format (one symptom–cause pairing per record):**
```json
{
  "record_id": "rec_000123",
  "plants": ["tomato"],
  "plant_groups": ["solanaceae"],
  "plant_parts": ["leaf"],
  "symptoms": ["yellowing", "brown_spots"],
  "location_patterns": ["lower_leaves_first"],
  "cause": "early blight",
  "cause_category": "disease",
  "summary": "1–3 sentence factual description, extracted from the source.",
  "distinguishing_questions": [
    {"question": "Do the spots have concentric rings?", "if_yes": "supports this cause", "if_no": "weakens this cause"}
  ],
  "next_actions": ["Remove affected lower leaves", "Avoid wetting foliage", "Monitor for 48 hours"],
  "inspect_next": ["Check undersides of leaves", "Check stem for lesions"],
  "caveats": "Anything the source says about uncertainty or lookalikes.",
  "source_id": "src_xyz",
  "source_url": "https://...",
  "status": "draft | reviewed"
}
```

**Deliverables**
- Vocab files, JSON Schema, and a `src/validate/` script that checks: schema validity, every symptom/plant/part id exists in the vocab, `source_id` exists in `sources.yaml`, required fields present.

**Accept when**
- Validator runs and passes on a hand-written sample of 5 records.
- **The VLM observation schema (separate task) must reuse these same symptom ids.** Export `symptoms.yaml` as the single source of truth for that task.

### Phase 3 — Ingest: source text → draft records
**Do**
- For each approved source, split into sections and draft records using a strong LLM run offline (build-time only). Prompt rules:
  - Extract only what the source states. Leave unknown fields null. No outside knowledge.
  - One record per symptom–cause pairing.
  - Map symptoms and plants to vocab ids. If a term has no match, output it under `unmapped_terms` instead of inventing an id.
  - Always copy `source_id` and `source_url`.
- Write drafts to `kb/records/draft/` with `status: draft`.
- Run the validator. Report unmapped terms so the owner can extend the vocabulary.

**Deliverables**
- Draft records for the Phase 1 scope; `unmapped_terms.txt` report.

**Accept when**
- All drafts pass validation. Vocabulary gaps are listed for the owner.

### Phase 4 — Human review
**Do**
- Produce a review sheet (CSV or markdown table): record id, plant, symptom, cause, summary, source link, with columns `approve / edit / reject`.
- Spot-check at minimum: 100% of records for the first plant group, then a random 20% per later batch. Raise the sample rate if error rate is high.
- Move approved records to `kb/records/reviewed/` with `status: reviewed`.

**Accept when**
- Only reviewed records exist in `reviewed/`. Error rate found in review is recorded (this tells us how much to trust later drafts).

### Phase 5 — Index build (the retrieval-quality core)

**Storage (default; confirm against hardware and runtime):**
- SQLite file `kb.sqlite` with tables: `records`, FTS5 virtual table over text fields, `edges` (symptom→cause→question→action relations), `plants`.
- Vector index built from reviewed records only. Use a SQLite vector extension or a local vector store (owner may choose; default to the simplest option that runs offline).

**What gets embedded and searched:**
- Build one **retrieval text** per record: summary + symptom labels and synonyms + cause + plant names and aliases. This bridges lay wording to technical wording.
- FTS5 indexes the same retrieval text plus `cause`, `distinguishing_questions`.
- Keep `summary`, `questions`, `actions`, and `source_url` as returned fields, not necessarily embedded.

**Retrieval function `retrieve(observation) -> list[Record]` — implement exactly this order:**
1. **Pre-filter (metadata), applied before any scoring:**
   - Plant known and confident → filter `plants` contains plant OR `plant_groups` contains the plant's group.
   - Plant unknown → no plant filter, but do not return plant-specific records ahead of generic ones without a flag.
   - `plant_parts`: filter if the observation names a part.
   - `symptoms`: require at least one overlapping symptom id with the observation (soft-fallback in step 5).
   - `cause_category`: only filter if the caller passes one (e.g., after a follow-up answer).
2. **Keyword search (BM25 via FTS5)** over the filtered set using the observation's symptom terms and plant names. Return top `N_kw` (default 20).
3. **Vector search** over the filtered set using the observation's text description. Return top `N_vec` (default 20).
4. **Fuse** the two ranked lists with Reciprocal Rank Fusion (default k=60).
5. **Cut to `K` results (default 5).** If the filtered set has fewer than a minimum viable count (default 3), relax the filter in this order and set `filters_relaxed` in the result: drop `plant_parts` → drop plant (keep group) → drop symptom overlap requirement.
6. **Optional reranker** (add only if Phase 6 shows it helps). Not in the first version.
7. **Return** the records plus metadata: which filters applied, which were relaxed, scores, and a `coverage` flag (`good | weak | none`) based on result count and top score. If `coverage` is `weak` or `none`, the model is instructed to say the knowledge base does not cover the case and ask questions instead of guessing.

**Follow-up question selection (use the graph edges):**
- From the top candidate causes, collect each record's `distinguishing_questions`.
- Prefer questions whose answers separate the top candidates (appear on one candidate but not others). Return 2–4 ranked questions.
- After the user answers, re-run `retrieve` with the new facts (e.g., `cause_category` hint, `location_patterns`) added.

**Deliverables**
- `build_index.py`, `retrieve.py`, a CLI such as `python -m src.retrieve --observation obs.json` that prints results with filters applied/relaxed.
- Tunables in one config file: `N_kw`, `N_vec`, `K`, RRF k, minimum viable count, embedding model name.

**Accept when**
- Index builds from `reviewed/` only, deterministically.
- `retrieve` returns results with metadata, and the filter-relaxation order works on contrived cases (unknown plant; unusual symptom; no match → `coverage: none`).

### Phase 6 — Retrieval evaluation (before any tuning)
**Do**
- Create `kb/eval/retrieval_set.jsonl`: 50–100 realistic queries. Each line: `{"query_observation": {...structured observation...}, "query_text": "lay wording", "expected_record_ids": [...], "notes": "..."}`.
- Include: lay phrasing vs technical phrasing, unknown plant, ambiguous symptoms (should return multiple candidates), and out-of-scope cases (expected `coverage: none`).
- Write `eval_retrieval.py`: report recall@K, MRR, and `coverage` accuracy; print a per-query list of misses.
- Compare configurations: vector only, keyword only, hybrid without pre-filter, hybrid with pre-filter. The pre-filter must be shown to help (or be removed/adjusted).
- Try at least two off-the-shelf embedding models; keep the best by recall@K.

**Accept when**
- Baseline numbers are recorded in `kb/eval/RESULTS.md` (with date, config, embedding model).
- Misses are categorized: (a) vocabulary mismatch, (b) missing record, (c) filter too strict, (d) ranking. Only (a) justifies embedding fine-tuning; (b) means add content; (c) means adjust the filter; (d) may justify a reranker.

### Phase 7 — Integration with the skill and model
**Do**
- Expose `retrieve` to the model as a tool, or call it from the application code after the VLM step (preferred: application code calls it; the model receives the results).
- The skill (SKILL.md) instructs the model to: use only retrieved records; cite which record each possibility came from; present 2–4 possibilities; use returned questions; respect `coverage` flags; ask the user when plant confidence is low.
- End-to-end test with the image set (separate task): photo → observation → retrieval → questions → answer.

**Accept when**
- Answers are grounded: every possible cause shown maps to a retrieved record. Run a groundedness check (an LLM judge or manual review on a sample) and record the result.

### Phase 8 — Iterate and expand
- Add plants in batches (repeat Phases 3–6 per batch). Re-run the retrieval eval after each batch to catch regressions.
- Only after Phase 6 evidence: consider embedding fine-tuning (use the retrieval set plus synthetic queries generated from records as training data) or a reranker.
- Keep `kb/eval/RESULTS.md` as a running log.

## 4. Guardrails for Claude Code

- Do not fetch or store a source whose license is unknown or disallows reuse; ask the owner.
- Do not write to `kb/records/reviewed/` — only the human review step does that.
- Do not hardcode plant facts from memory into records, vocab descriptions, or prompts.
- Never index `draft/` records.
- When unsure about scope, sources, or hardware: stop and ask.
- Keep all tunable numbers in config, not scattered in code.
- After each phase, run the validator and the relevant tests and report results before moving on.

## 5. Definition of done (v1)

- [ ] Scope and sources documented with licenses.
- [ ] Vocabulary files and record schema finalized and shared with the VLM observation schema.
- [ ] Reviewed records for the chosen scope, all passing validation.
- [ ] Index builds reproducibly from reviewed records.
- [ ] Retrieval pipeline implements pre-filter → BM25 + vector → RRF → top-K with filter relaxation and coverage flag.
- [ ] Retrieval eval set (50+ queries) with recorded baseline and comparison of configurations.
- [ ] End-to-end groundedness check recorded.
