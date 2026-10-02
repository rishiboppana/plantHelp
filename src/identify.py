"""Plant identification with calibrated confidence. One self-reported guess is unreliable, so three independent looks are combined:
 A) describe the visible features first, then name candidates; B) a direct, conservative guess; C) name the best match AND its closest
lookalike, and say whether the feature that separates them is actually visible. Confidence comes from agreement, not from the model's claim.
Usage: python -m src.identify photo.jpg
"""
import json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import yaml
from src.validate.validate import KB

PROMPT_A = ("Look at the plant in the photo. First list the visible features that matter for identification: leaf shape and size, margins, "
            "venation, how leaves attach (rosette, alternate, opposite, clustered), stem or trunk, growth habit (upright, trailing, bushy), "
            "flowers or fruit. Then name up to 3 candidate plants, best first, with a confidence 0-100 for each based ONLY on those features. "
            "If the features do not clearly separate similar plants, lower the confidence and include the lookalike. If no plant is clearly "
            'visible, return an empty list. Output ONLY JSON: {"features": "...", "candidates": [{"name": "common name", "confidence": 0}]}')
PROMPT_B = ("What plant is this? Give up to 3 candidates, best first, each with a confidence 0-100. Be conservative: many plants look alike, so "
            'do not go above 80 unless the features are unmistakable. If no plant is clearly visible, return an empty list. '
            'Output ONLY JSON: {"candidates": [{"name": "common name", "confidence": 0}]}')
PROMPT_C = ("Name the single most likely plant in the photo. Then name its most similar lookalike (a different plant people confuse it with), "
            "give one visible feature that tells them apart, and say honestly whether you can actually see that feature in this photo. "
            'Output ONLY JSON: {"best": "common name", "lookalike": "common name", "feature": "...", "feature_visible": true}')


def _known():
    pl = yaml.safe_load((KB / "vocab" / "plants.yaml").read_text())["plants"]
    m = {}
    for p in pl:
        for n in p["names"] + p.get("aliases", []) + [p["scientific"]]:
            m[_basic(n)] = p["names"][0].lower()
    return m


def _basic(name):
    n = re.sub(r"\(.*?\)", " ", str(name).lower())
    n = re.sub(r"[^a-z0-9' ]", " ", n)
    n = re.sub(r"\b(common|indoor|house|houseplant|plant|tree)\b", " ", n)
    return " ".join(n.split())


KNOWN = _known()


def canon(name):
    """Common name for a candidate; species and cultivars of a known plant fold into it (ficus elastica 'burgundy' -> rubber plant)."""
    b = _basic(name)
    if b in KNOWN: return KNOWN[b]
    for k in sorted(KNOWN, key=len, reverse=True):
        if b.startswith(k + " "): return KNOWN[k]
    return b


def key(name):
    """Agreement key: two candidates in the same genus-like first word agree (calathea lancifolia ~ calathea ornata)."""
    return name.split(" ")[0] if name else ""


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


# Independent model families used as a second and third opinion. Same-family samples share one bias, so agreement across
# families is what raises confidence. Override with PLANTLENS_ID_MODELS="model:provider,model:provider".
CROSS_MODELS = [m for m in os.environ.get("PLANTLENS_ID_MODELS", "").split(",") if m] or [
    "google/gemma-4-31B-it:novita", "meta-llama/Llama-4-Scout-17B-16E-Instruct:novita"]


def _cross(photo):
    """First candidate from each other model family (None when a model is unavailable)."""
    from src.remote_vlm import RemoteVLM

    def one(model):
        try:
            d = _json(RemoteVLM(model=model, timeout=60).chat(
                [{"role": "user", "content": [{"type": "image_path", "path": photo}, {"type": "text", "text": PROMPT_B}]}], 400, 0.2))
            c = (d or {}).get("candidates") or []
            return canon(c[0].get("name", "")) if c else None
        except Exception:
            return None
    with ThreadPoolExecutor(len(CROSS_MODELS)) as ex:
        return list(ex.map(one, CROSS_MODELS))


def identify(vlm, photo, cross=True):
    """Returns {"name", "confidence": high|medium|low, "candidates": [...], "votes": n} (name is None when confidence is low)."""
    img = [{"type": "image_path", "path": photo}]
    asks = [(PROMPT_A, 0.0), (PROMPT_B, 0.6), (PROMPT_C, 0.6)]

    def run(a):
        try:
            return _json(vlm.chat([{"role": "user", "content": img + [{"type": "text", "text": a[0]}]}], 500, a[1]))
        except Exception:
            return None
    with ThreadPoolExecutor(4) as ex:
        fut = ex.submit(_cross, photo) if cross else None
        A, B, C = list(ex.map(run, asks))
        others = fut.result() if fut else []

    tops, confs, pool = [], [], []
    for d in (A, B):
        c = (d or {}).get("candidates") or []
        if c:
            tops.append(canon(c[0].get("name", ""))); confs.append(float(c[0].get("confidence", 0) or 0))
            pool += [canon(x.get("name", "")) for x in c]
    best = canon((C or {}).get("best", "")) if C else ""
    look = canon((C or {}).get("lookalike", "")) if C else ""
    if best: tops.append(best)
    tops = [t for t in tops if t]
    if not tops:
        return {"name": None, "confidence": "low", "candidates": [], "votes": 0}
    keys = [key(t) for t in tops]
    lead_key = max(set(keys), key=lambda k: (keys.count(k), -keys.index(k)))
    group = [t for t in tops if key(t) == lead_key]
    lead = group[0] if len(set(group)) == 1 else lead_key          # same genus, different species: name only the genus
    votes = len(group)
    visible = bool((C or {}).get("feature_visible")) if C else False
    clear = (C or {}).get("subject_clear", True) is not False
    mean_conf = sum(confs) / len(confs) if confs else 0
    # families: Qwen's own verdict (its three looks must agree) plus one vote from each other family
    answered = [o for o in others if o]
    agree = 1 + sum(1 for o in answered if key(o) == lead_key)
    families = 1 + len(answered)
    inner = votes == len(tops) and votes >= 2
    if families >= 3 and agree == families and inner and clear: level = "high"
    elif agree >= 2 and agree > families / 2 and inner: level = "medium"      # a majority of families agree
    elif families == 1 and inner and votes >= 3 and visible and clear and mean_conf >= 65: level = "medium"   # no second opinion: never "high"
    else: level = "low"
    if not clear and level == "high": level = "medium"
    seen, cands = set(), []
    for x in [lead] + answered + pool + [best, look if not visible else ""]:
        if x and key(x) not in seen and (x == lead or key(x) != lead_key): seen.add(key(x)); cands.append(x)
    return {"name": lead if level != "low" else None, "confidence": level, "candidates": cands[:3], "votes": votes, "agree": f"{agree}/{families}", "subject_clear": clear}


if __name__ == "__main__":
    from src.remote_vlm import RemoteVLM
    print(json.dumps(identify(RemoteVLM(), sys.argv[1]), indent=1))
