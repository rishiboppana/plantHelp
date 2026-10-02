"""Build kb/index/kb.sqlite from kb/records/reviewed ONLY. Deterministic. Usage: python -m src.build_index [--embedder NAME]"""
import argparse, json, sqlite3, struct
from pathlib import Path
import yaml
from src.embed import get_encoder
from src.validate.validate import KB, load_vocab, iter_records, validate_record
from jsonschema import Draft202012Validator

ROOT = KB.parent


def load_config():
    return yaml.safe_load((KB / "config.yaml").read_text())


def _synonyms():
    d = yaml.safe_load((KB / "vocab" / "symptoms.yaml").read_text())
    sym = {s["id"]: [s["label"]] + s.get("synonyms", []) for s in d["symptoms"]}
    loc = {s["id"]: [s["label"]] + s.get("synonyms", []) for s in d["location_patterns"]}
    plants = {p["id"]: p["names"] + p.get("aliases", []) + [p["scientific"]] for p in yaml.safe_load((KB / "vocab" / "plants.yaml").read_text())["plants"]}
    parts = {p["id"]: [p["label"]] for p in yaml.safe_load((KB / "vocab" / "plant_parts.yaml").read_text())["plant_parts"]}
    return sym, loc, plants, parts


def retrieval_text(rec, sym, loc, plants, parts):
    bits = [rec["summary"], rec["cause"]]
    for s in rec["symptoms"]: bits += sym[s]
    for s in rec.get("location_patterns", []): bits += loc[s]
    for p in rec["plants"]: bits += plants[p]
    for p in rec["plant_parts"]: bits += parts[p]
    return " . ".join(bits)


def pack(v): return struct.pack(f"{len(v)}f", *v)


def build(embedder=None, path=None):
    cfg = load_config()
    name = embedder or cfg["embedder"]
    vocab = load_vocab()
    validator = Draft202012Validator(json.loads((KB / "schema" / "record.schema.json").read_text()))
    recs = []
    for where, r in iter_records([KB / "records" / "reviewed"]):
        errs = validate_record(r, vocab, validator)
        if errs or r.get("status") != "reviewed":
            raise SystemExit(f"refusing to index {where}: {errs or 'status != reviewed'}")
        recs.append(r)
    recs.sort(key=lambda r: r["record_id"])
    sym, loc, plants, parts = _synonyms()
    texts = [retrieval_text(r, sym, loc, plants, parts) for r in recs]
    vecs = get_encoder(name)(texts)

    path = Path(path) if path else ROOT / cfg["index_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): path.unlink()
    db = sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE records(record_id TEXT PRIMARY KEY, rid INTEGER UNIQUE, json TEXT, retrieval_text TEXT, vec BLOB);
      CREATE VIRTUAL TABLE records_fts USING fts5(retrieval_text, cause, questions, tokenize='porter unicode61');
      CREATE TABLE edges(src TEXT, relation TEXT, dst TEXT, record_id TEXT);
      CREATE TABLE rec_plants(record_id TEXT, plant TEXT);
      CREATE TABLE rec_groups(record_id TEXT, grp TEXT);
      CREATE TABLE rec_parts(record_id TEXT, part TEXT);
      CREATE TABLE rec_symptoms(record_id TEXT, symptom TEXT);
    """)
    db.execute("INSERT INTO meta VALUES('embedder', ?)", (name,))
    for i, (r, t, v) in enumerate(zip(recs, texts, vecs), 1):
        rid = r["record_id"]
        db.execute("INSERT INTO records VALUES(?,?,?,?,?)", (rid, i, json.dumps(r, sort_keys=True), t, pack(v)))
        qs = " ".join(q["question"] for q in r["distinguishing_questions"])
        db.execute("INSERT INTO records_fts(rowid, retrieval_text, cause, questions) VALUES(?,?,?,?)", (i, t, r["cause"], qs))
        for p in r["plants"]: db.execute("INSERT INTO rec_plants VALUES(?,?)", (rid, p))
        for g in r["plant_groups"]: db.execute("INSERT INTO rec_groups VALUES(?,?)", (rid, g))
        for p in r["plant_parts"]: db.execute("INSERT INTO rec_parts VALUES(?,?)", (rid, p))
        for s in r["symptoms"]:
            db.execute("INSERT INTO rec_symptoms VALUES(?,?)", (rid, s))
            db.execute("INSERT INTO edges VALUES(?,?,?,?)", (s, "indicates", r["cause"], rid))
        for q in r["distinguishing_questions"]:
            db.execute("INSERT INTO edges VALUES(?,?,?,?)", (r["cause"], "asks", q["question"], rid))
        for a in r["next_actions"]:
            db.execute("INSERT INTO edges VALUES(?,?,?,?)", (r["cause"], "action", a, rid))
    db.commit(); db.close()
    print(f"indexed {len(recs)} reviewed records with embedder '{name}' -> {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--embedder"); build(ap.parse_args().embedder)
