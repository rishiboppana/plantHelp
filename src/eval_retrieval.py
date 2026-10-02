"""Retrieval evaluation: recall@K, MRR, coverage accuracy, per-query misses, config comparison.
Usage: python -m src.eval_retrieval [--embedder hash] [--misses] [--write-md]"""
import argparse, json, datetime
from pathlib import Path
from src.build_index import load_config, ROOT
from src.retrieve import retrieve

CONFIGS = [("vector only", dict(mode="vector", prefilter=False)), ("keyword only", dict(mode="keyword", prefilter=False)),
           ("hybrid, no prefilter", dict(mode="hybrid", prefilter=False)), ("hybrid + prefilter", dict(mode="hybrid", prefilter=True))]


def run(queries, K, **kw):
    rows = []
    for q in queries:
        out = retrieve(q["query_observation"], **kw)
        got = [r["record"]["record_id"] for r in out["results"]][:K]
        exp = q["expected_record_ids"]
        rows.append({"q": q, "got": got, "out": out})
    return rows


def metrics(rows, K):
    ins = [r for r in rows if r["q"]["expected_coverage"] == "in_scope"]
    recall = sum(len(set(r["got"]) & set(r["q"]["expected_record_ids"])) / len(r["q"]["expected_record_ids"]) for r in ins) / len(ins)
    hit = sum(bool(set(r["got"]) & set(r["q"]["expected_record_ids"])) for r in ins) / len(ins)
    mrr = 0.0
    for r in ins:
        for i, rid in enumerate(r["got"], 1):
            if rid in r["q"]["expected_record_ids"]: mrr += 1 / i; break
    mrr /= len(ins)
    cov_ok = sum((r["out"]["coverage"] == "none") == (r["q"]["expected_coverage"] == "none") for r in rows) / len(rows)
    return {"recall@K": recall, "hit@K": hit, "MRR": mrr, "coverage_acc": cov_ok}


def classify_miss(r):
    """(a) vocabulary mismatch, (b) missing record, (c) filter too strict, (d) ranking."""
    q, out = r["q"], r["out"]
    miss = [e for e in q["expected_record_ids"] if e not in r["got"]]
    cats = []
    for e in miss:
        if e not in out["debug"]["filtered_ids"]: cats.append("c")
        elif e not in out["debug"]["keyword_ids"] and e not in out["debug"]["vector_ids"]: cats.append("a")
        else: cats.append("d")
    return sorted(set(cats))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--embedder"); ap.add_argument("--misses", action="store_true"); ap.add_argument("--write-md", action="store_true")
    a = ap.parse_args()
    cfg = load_config(); K = cfg["K"]
    queries = [json.loads(l) for l in (ROOT / "kb/eval/retrieval_set.jsonl").read_text().splitlines() if l.strip()]
    import sqlite3
    emb = sqlite3.connect(ROOT / cfg["index_path"]).execute("SELECT value FROM meta WHERE key='embedder'").fetchone()[0]
    lines = [f"| config | recall@{K} | hit@{K} | MRR | coverage acc |", "|---|---|---|---|---|"]
    detail = None
    for name, kw in CONFIGS:
        rows = run(queries, K, embedder=a.embedder, **kw)
        m = metrics(rows, K)
        lines.append(f"| {name} | {m['recall@K']:.3f} | {m['hit@K']:.3f} | {m['MRR']:.3f} | {m['coverage_acc']:.3f} |")
        if name == "hybrid + prefilter": detail = rows
    table = "\n".join(lines)
    print(f"embedder: {emb} | {len(queries)} queries\n{table}")
    miss_lines, cat_count = [], {}
    for r in detail:
        q = r["q"]
        if q["expected_coverage"] == "none":
            if r["out"]["coverage"] != "none": miss_lines.append(f"- {q['id']} [oos] expected none, got {r['out']['coverage']}: {q['query_text']}")
            continue
        if set(r["got"]) & set(q["expected_record_ids"]) == set(q["expected_record_ids"]): continue
        cats = classify_miss(r)
        for c in cats: cat_count[c] = cat_count.get(c, 0) + 1
        miss_lines.append(f"- {q['id']} [{q['kind']}] ({','.join(cats)}) {q['query_text']}  expected={q['expected_record_ids']} got={r['got']}")
    print(f"\nmisses in hybrid+prefilter (a=vocab, c=filter too strict, d=ranking; b needs human judgement): {cat_count}")
    if a.misses: print("\n".join(miss_lines))
    if a.write_md:
        md = ROOT / "kb/eval/RESULTS.md"
        entry = (f"\n## {datetime.date.today()} — embedder `{emb}`\n\n{len(queries)} queries (in-scope + out-of-scope), K={K}, "
                 f"config: rrf_k={cfg['rrf_k']}, N_kw={cfg['N_kw']}, N_vec={cfg['N_vec']}, min_viable={cfg['min_viable']}, vec_min_score={cfg['vec_min_score']}\n\n{table}\n\n"
                 f"Miss categories (hybrid + prefilter): {cat_count or 'none'}\n\n<details><summary>Misses</summary>\n\n" + "\n".join(miss_lines) + "\n\n</details>\n")
        md.write_text((md.read_text() if md.exists() else "# Retrieval results (running log)\n") + entry)
        print("appended to", md)


if __name__ == "__main__":
    main()
