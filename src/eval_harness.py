"""Harness benchmark: the full PlantLens pipeline vs. a plain single model call, on labelled photos.
Both arms use the same open-weight model and the same symptom vocabulary; only the harness differs
(photo verification of each symptom, vocabulary check with retry, multi-family plant ID vote).
Labels live in kb/eval/photo_set.jsonl, one JSON per line: {"photo": "test_photos/x.jpg", "health": "healthy|possible_problem", "symptoms": [ids], "plant": "pothos"}
Usage: python -m src.eval_harness --init            # write a label template for the photos in test_photos/
       python -m src.eval_harness [--write-md]      # run both arms (needs HF_TOKEN or a local PLANTLENS_BASE_URL)"""
import argparse, datetime, json
from pathlib import Path
from src.pipeline import Session, SYMPTOMS, SYSTEM, parse_json, clean_observation
from src.remote_vlm import RemoteVLM

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "kb" / "eval" / "photo_set.jsonl"
RESULTS = ROOT / "kb" / "eval" / "HARNESS_RESULTS.md"


def baseline(vlm, photo):
    """One model call, same skill text and vocabulary, no verification, no retry, no plant-ID vote."""
    ask = "Output ONLY the observation JSON described in the skill. Use only symptom ids from the symptom reference."
    reply = vlm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": [{"type": "image_path", "path": photo}, {"type": "text", "text": ask}]}], 500, 0.0, "Baseline")
    try: obs, _ = clean_observation(parse_json(reply))
    except Exception: obs = {"health": "unclear", "symptoms": [], "plant": {}}
    return obs


def harness(vlm, photo):
    return Session(vlm).ensure_observation(photo, "")


def score(rows):
    """rows: [(label, observation)]. Micro precision/recall/F1 over symptoms, health accuracy, false alarms on healthy photos, plant accuracy."""
    tp = fp = fn = 0; ok = 0; healthy = alarms = 0; pl_ok = pl_n = 0
    for lab, obs in rows:
        want, got = set(lab.get("symptoms", [])), set(obs.get("symptoms", [])) & SYMPTOMS
        tp += len(want & got); fp += len(got - want); fn += len(want - got)
        pred = "healthy" if obs.get("health") == "healthy" else "possible_problem" if obs.get("health") == "possible_problem" or got else "unclear"
        ok += pred == lab["health"]
        if lab["health"] == "healthy":
            healthy += 1; alarms += bool(got)
        if lab.get("plant"):
            pl_n += 1; name = ((obs.get("plant") or {}).get("name") or "").lower(); pl_ok += lab["plant"].lower() in name or name in lab["plant"].lower() and bool(name)
    p = tp / (tp + fp) if tp + fp else 0.0; r = tp / (tp + fn) if tp + fn else 0.0
    return {"n": len(rows), "health_acc": ok / len(rows) if rows else 0.0, "precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0,
            "false_alarm_rate": alarms / healthy if healthy else 0.0, "plant_acc": pl_ok / pl_n if pl_n else None}


def run(labels, vlm):
    out = {}
    for name, fn in (("baseline (single call)", baseline), ("PlantLens harness", harness)):
        rows = []
        for lab in labels:
            try: obs = fn(vlm, str(ROOT / lab["photo"]))
            except Exception: obs = {"health": "unclear", "symptoms": [], "plant": {}}
            rows.append((lab, obs))
        out[name] = score(rows)
    return out


def table(res):
    cols = [("health_acc", "Health acc."), ("precision", "Symptom precision"), ("recall", "Symptom recall"), ("f1", "Symptom F1"), ("false_alarm_rate", "False alarms on healthy"), ("plant_acc", "Plant ID acc.")]
    f = lambda v: "n/a" if v is None else f"{v:.2f}"
    return "\n".join(["| Arm | " + " | ".join(c[1] for c in cols) + " |", "|---|" + "---|" * len(cols)]
                     + [f"| {k} | " + " | ".join(f(v[c[0]]) for c in cols) + " |" for k, v in res.items()])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--init", action="store_true"); ap.add_argument("--write-md", action="store_true"); a = ap.parse_args()
    if a.init:
        photos = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "test_photos").iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        LABELS.write_text("".join(json.dumps({"photo": p, "health": "", "symptoms": [], "plant": ""}) + "\n" for p in photos))
        print(f"wrote {len(photos)} blank labels to {LABELS}; fill in health (healthy|possible_problem), symptoms (ids from kb/vocab/symptoms.yaml) and plant"); return
    labels = [json.loads(l) for l in LABELS.read_text().splitlines() if l.strip()]
    labels = [l for l in labels if l.get("health")]
    if not labels: raise SystemExit("no labelled photos; run --init and fill in kb/eval/photo_set.jsonl")
    res = run(labels, RemoteVLM()); t = table(res); print(t)
    if a.write_md:
        RESULTS.write_text(f"# Harness benchmark\n\n{datetime.date.today()} · {len(labels)} labelled photos · same open-weight model in both arms\n\n{t}\n")


if __name__ == "__main__": main()
