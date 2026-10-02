"""Hybrid retrieval: metadata pre-filter -> BM25 + vector -> RRF -> top-K, with filter relaxation and coverage flag.

Observation (dict):
  {"plant": {"id": "pothos"|None, "confidence": "high"|"low"|"unknown"},
   "plant_parts": [...], "symptoms": [...], "location_patterns": [...], "description": "free text"}
CLI: python -m src.retrieve --observation obs.json [--category pest] [--embedder hash]
"""
import argparse, json, re, sqlite3, struct, sys
from pathlib import Path
import yaml
from src.build_index import load_config, ROOT, _synonyms
from src.embed import get_encoder, cosine
from src.validate.validate import KB

_encoders = {}


def _encoder(name):
    if name not in _encoders: _encoders[name] = get_encoder(name)
    return _encoders[name]


def _unpack(b): return list(struct.unpack(f"{len(b)//4}f", b))


def _plant_group(plant_id):
    for p in yaml.safe_load((KB / "vocab" / "plants.yaml").read_text())["plants"]:
        if p["id"] == plant_id: return p["group"]
    return None


def _query_terms(obs):
    sym, loc, plants, _ = _synonyms()
    terms = []
    for s in obs.get("symptoms", []): terms += sym.get(s, [s])
    for s in obs.get("location_patterns", []): terms += loc.get(s, [s])
    p = obs.get("plant") or {}
    if p.get("id") and p.get("confidence") == "high": terms += plants.get(p["id"], [p["id"]])
    return terms


STOP = set("the and for are was but not you all any can had her his its our out has how who why what when with from that this have there their they them then than into about after before while where which would could should plant plants leaf leaves look looks like just now seems seem right still".split())


def _fts_query(terms, description):
    words = set()
    for t in terms + ([description] if description else []):
        words.update(w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2 and w not in STOP)
    return " OR ".join(sorted(words))


def retrieve(observation, cause_category=None, embedder=None, db_path=None, mode="hybrid", prefilter=True):
    """mode: hybrid | keyword | vector (the latter two exist for the Phase 6 comparison). prefilter=False scores all records."""
    cfg = load_config()
    db = sqlite3.connect(db_path or ROOT / cfg["index_path"])
    index_embedder = db.execute("SELECT value FROM meta WHERE key='embedder'").fetchone()[0]
    if embedder and embedder != index_embedder:
        raise ValueError(f"index built with '{index_embedder}', asked for '{embedder}'")
    enc = _encoder(index_embedder)

    plant = observation.get("plant") or {}
    plant_known = bool(plant.get("id")) and plant.get("confidence") == "high"
    group = _plant_group(plant["id"]) if plant_known else None
    parts = observation.get("plant_parts", [])
    symptoms = observation.get("symptoms", [])

    def ids_for(use_parts, use_plant, use_symptoms):
        q, args = "SELECT record_id FROM records r WHERE 1=1", []
        if use_plant and plant_known:
            # generic records (no plant or group listed) always pass the plant filter
            q += (" AND (EXISTS(SELECT 1 FROM rec_plants p WHERE p.record_id=r.record_id AND p.plant=?)"
                  " OR EXISTS(SELECT 1 FROM rec_groups g WHERE g.record_id=r.record_id AND g.grp=?)"
                  " OR (NOT EXISTS(SELECT 1 FROM rec_plants p WHERE p.record_id=r.record_id)"
                  "     AND NOT EXISTS(SELECT 1 FROM rec_groups g WHERE g.record_id=r.record_id)))")
            args += [plant["id"], group]
        if use_parts and parts:
            # whole_plant records apply to any part (Phase 6: strict part match dropped such records)
            q += " AND EXISTS(SELECT 1 FROM rec_parts x WHERE x.record_id=r.record_id AND x.part IN (%s))" % ",".join("?" * (len(parts) + 1))
            args += list(parts) + ["whole_plant"]
        if use_symptoms and symptoms:
            q += " AND EXISTS(SELECT 1 FROM rec_symptoms s WHERE s.record_id=r.record_id AND s.symptom IN (%s))" % ",".join("?" * len(symptoms))
            args += symptoms
        if cause_category:
            q += " AND json_extract(r.json,'$.cause_category')=?"
            args.append(cause_category)
        return {r[0] for r in db.execute(q, args)}

    applied = {"plant": plant_known, "plant_parts": bool(parts), "symptoms": bool(symptoms), "cause_category": bool(cause_category)}
    relaxed = []
    ids = ids_for(True, True, True)
    if not prefilter:
        ids = {r[0] for r in db.execute("SELECT record_id FROM records")}
    for step, flags in (("plant_parts", (False, True, True)), ("plant", (False, False, True)), ("symptoms", (False, False, False))):
        if not prefilter or len(ids) >= cfg["min_viable"]: break
        ids = ids_for(*flags)
        relaxed.append(step)

    terms = _query_terms(observation)
    description = observation.get("description", "")
    ranked_kw, kw_hit = [], set()
    fq = _fts_query(terms, description)
    if fq and ids:
        rows = db.execute("SELECT r.record_id FROM records_fts f JOIN records r ON r.rid=f.rowid "
                          "WHERE records_fts MATCH ? ORDER BY bm25(records_fts) LIMIT 200", (fq,)).fetchall()
        ranked_kw = [r[0] for r in rows if r[0] in ids][:cfg["N_kw"]]
        kw_hit = set(ranked_kw)

    qvec = enc([" . ".join([description] + terms)])[0]
    sims = {}
    for rid, blob in db.execute("SELECT record_id, vec FROM records"):
        if rid in ids: sims[rid] = cosine(qvec, _unpack(blob))
    ranked_vec = sorted(sims, key=lambda r: (-sims[r], r))[:cfg["N_vec"]]

    fused = {}
    for ranking in ((ranked_kw, ranked_vec) if mode == "hybrid" else (ranked_kw,) if mode == "keyword" else (ranked_vec,)):
        for pos, rid in enumerate(ranking, 1):
            fused[rid] = fused.get(rid, 0.0) + 1.0 / (cfg["rrf_k"] + pos)
    top = sorted(fused, key=lambda r: (-fused[r], r))[:cfg["K"]]

    sym_set = set(symptoms)
    results = []
    for rid in top:
        rec = json.loads(db.execute("SELECT json FROM records WHERE record_id=?", (rid,)).fetchone()[0])
        overlap = sorted(sym_set & set(rec["symptoms"]))
        results.append({"record": rec, "score": round(fused[rid], 5), "cosine": round(sims.get(rid, 0.0), 3),
                        "keyword_hit": rid in kw_hit, "symptom_overlap": overlap})

    def evidence(r): return r["keyword_hit"] or r["cosine"] >= cfg["vec_min_score"]
    if not results or not any(r["symptom_overlap"] or evidence(r) for r in results):
        coverage = "none"
    elif results[0]["symptom_overlap"] and evidence(results[0]):
        coverage = "good"
    else:
        coverage = "weak"
    if coverage == "none": results = []

    return {"results": results, "coverage": coverage, "filters_applied": applied, "filters_relaxed": relaxed,
            "questions": select_questions([r["record"] for r in results], cfg["n_questions"]),
            "debug": {"filtered_ids": sorted(ids), "keyword_ids": ranked_kw, "vector_ids": ranked_vec}}


def select_questions(records, n):
    """Prefer questions tied to one candidate; round-robin across candidates in rank order."""
    per = []
    for r in records:
        per.append([{"question": q["question"], "supports": r["cause"], "record_id": r["record_id"]} for q in r["distinguishing_questions"]])
    out, seen, i = [], set(), 0
    while len(out) < n and any(per):
        for qs in per:
            if qs and len(out) < n:
                q = qs.pop(0)
                if q["question"] not in seen:
                    seen.add(q["question"]); out.append(q)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--observation", required=True); ap.add_argument("--category"); ap.add_argument("--embedder")
    a = ap.parse_args()
    out = retrieve(json.loads(Path(a.observation).read_text()), a.category, a.embedder)
    print(f"coverage: {out['coverage']} | applied: {out['filters_applied']} | relaxed: {out['filters_relaxed']}")
    for r in out["results"]:
        print(f"  {r['record']['record_id']}  {r['record']['cause']:<42} score={r['score']} cos={r['cosine']} kw={r['keyword_hit']} overlap={r['symptom_overlap']}")
    print("questions:")
    for q in out["questions"]: print(f"  - {q['question']}  [{q['supports']}]")


if __name__ == "__main__":
    main()
