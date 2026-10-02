"""Graph RAG explorer (read-only; imports existing code, modifies nothing).
Run from repo root:  python3 -m graph_ui.server   ->  http://localhost:8765
"""
import json, re, sqlite3, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.build_index import load_config, _synonyms  # noqa: E402
from src.retrieve import retrieve  # noqa: E402
from src.validate.validate import KB  # noqa: E402

CFG = load_config()
DB_PATH = ROOT / CFG["index_path"]
FALLBACK = Path(__file__).parent / "fallback_hash.sqlite"


def _use_fallback_if_needed():
    """If the real embedder isn't installed here, build a throwaway hash-embedding index next to this file (the real index is untouched)."""
    global DB_PATH
    name = sqlite3.connect(DB_PATH).execute("SELECT value FROM meta WHERE key='embedder'").fetchone()[0]
    try:
        from src.embed import get_encoder
        get_encoder(name)
    except Exception:
        import src.build_index as bi
        bi.load_config = lambda: {**CFG, "index_path": str(FALLBACK.relative_to(ROOT))}
        bi.build("hash")
        DB_PATH = FALLBACK
        print(f"embedder '{name}' unavailable -> using hash fallback index (vector scores are approximate)")


_use_fallback_if_needed()


def first_sentence(t, n=140):
    s = re.split(r"(?<=[.!?])\s", t.strip())[0]
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def build_graph():
    """Nodes/edges mirror the `edges` table in the index (symptom -indicates-> cause -asks/action->) plus plant/part links."""
    vocab = yaml.safe_load((KB / "vocab" / "symptoms.yaml").read_text())
    plants = {p["id"]: p for p in yaml.safe_load((KB / "vocab" / "plants.yaml").read_text())["plants"]}
    parts = {p["id"]: p for p in yaml.safe_load((KB / "vocab" / "plant_parts.yaml").read_text())["plant_parts"]}
    sym = {s["id"]: s for s in vocab["symptoms"]}
    nodes, edges = {}, []

    def node(i, type_, label, line, **kw):
        nodes.setdefault(i, {"id": i, "type": type_, "label": label, "line": line, **kw})

    db = sqlite3.connect(DB_PATH)
    for (js,) in db.execute("SELECT json FROM records ORDER BY record_id"):
        r = json.loads(js)
        rid = "rec:" + r["record_id"]
        node(rid, "cause", r["cause"], first_sentence(r["summary"]), category=r["cause_category"],
             record_id=r["record_id"], summary=r["summary"], caveats=r.get("caveats", ""), source=r.get("source_url", ""))
        for s in r["symptoms"]:
            s_meta = sym[s]
            node("sym:" + s, "symptom", s_meta["label"], "Also seen as: " + ", ".join(s_meta.get("synonyms", [])[:4]), key=s)
            edges.append({"s": "sym:" + s, "t": rid, "rel": "indicates"})
        for q in r["distinguishing_questions"]:
            qid = "q:" + q["question"]
            node(qid, "question", q["question"], f"Yes → {q['if_yes']}; No → {q['if_no']}")
            edges.append({"s": rid, "t": qid, "rel": "asks"})
        for a in r["next_actions"]:
            node("act:" + a, "action", a, "Recommended next action")
            edges.append({"s": rid, "t": "act:" + a, "rel": "action"})
        for p in r["plants"]:
            node("plant:" + p, "plant", plants[p]["names"][0], f"{plants[p]['scientific']} ({plants[p]['group']})", key=p)
            edges.append({"s": rid, "t": "plant:" + p, "rel": "applies_to"})
        for p in r["plant_parts"]:
            node("part:" + p, "part", parts[p]["label"], "Plant part where this shows up", key=p)
            edges.append({"s": rid, "t": "part:" + p, "rel": "on_part"})
    return {"nodes": list(nodes.values()), "edges": edges, "embedder": db.execute("SELECT value FROM meta WHERE key='embedder'").fetchone()[0],
            "config": {k: CFG[k] for k in ("N_kw", "N_vec", "K", "rrf_k", "min_viable", "vec_min_score")}}


def parse_query(text):
    """UI-only helper: free text -> structured observation by matching vocab synonyms (the real app gets this from the VLM)."""
    low = " " + re.sub(r"[^a-z0-9' ]", " ", text.lower()) + " "
    words = set(low.split())
    sym, loc, plants, parts = _synonyms()

    def hits(table):
        out = []
        for i, names in table.items():
            if any(" " + re.sub(r"[^a-z0-9' ]", " ", n.lower()).strip() + " " in low or
                   (len(n.split()) > 1 and all(w in words for w in n.lower().split())) for n in names): out.append(i)
        return out

    symptoms, locs = hits(sym), hits(loc)
    pl = hits(plants)
    pt = hits({k: v + [k, k + "s"] for k, v in parts.items() if k != "whole_plant"})
    if "leaves" in words and "leaf" not in pt: pt.append("leaf")
    if "soil" in low and "soil" not in pt: pt.append("soil")
    return {"plant": {"id": pl[0], "confidence": "high"} if pl else {"id": None, "confidence": "unknown"},
            "plant_parts": pt, "symptoms": symptoms, "location_patterns": locs, "description": text}


def run_query(body):
    obs = parse_query(body.get("text", ""))
    for k in ("symptoms", "plant_parts", "location_patterns"):
        if isinstance(body.get(k), list): obs[k] = body[k]
    if body.get("plant_id") is not None:
        obs["plant"] = {"id": body["plant_id"] or None, "confidence": "high" if body["plant_id"] else "unknown"}
    out = retrieve(obs, body.get("cause_category") or None, db_path=DB_PATH, mode=body.get("mode", "hybrid"), prefilter=body.get("prefilter", True))
    return {"observation": obs, "coverage": out["coverage"], "filters_applied": out["filters_applied"],
            "filters_relaxed": out["filters_relaxed"], "debug": out["debug"], "questions": out["questions"],
            "results": [{"record_id": r["record"]["record_id"], "cause": r["record"]["cause"], "score": r["score"],
                         "cosine": r["cosine"], "keyword_hit": r["keyword_hit"], "symptom_overlap": r["symptom_overlap"]}
                        for r in out["results"]]}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/graph": self._send(200, build_graph())
        elif self.path in ("/", "/index.html"): self._send(200, (Path(__file__).parent / "index.html").read_bytes(), "text/html; charset=utf-8")
        else: self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/query": return self._send(404, {"error": "not found"})
        try:
            self._send(200, run_query(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")))
        except Exception as e:  # surface to the UI instead of dropping the connection
            self._send(500, {"error": str(e)})

    def log_message(self, *a): pass


if __name__ == "__main__":
    print("Graph RAG explorer: http://localhost:8765")
    HTTPServer(("127.0.0.1", 8765), H).serve_forever()
