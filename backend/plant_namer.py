"""Gives each plant its own name, written by the model. A plant that still has a placeholder name ("New plant", "My first plant") is
named once the chat or a photo shows what it is, e.g. "Jasper the Jade plant". The model invents the name; code only guarantees it is unique."""
import json, re
import db
from fastapi import APIRouter
from src import trace

router = APIRouter(prefix="/api/plants", tags=["plants"])
PLACEHOLDERS = {"new plant", "my first plant", ""}

PROMPT = """You name houseplants. From the evidence below, decide what kind of plant this is, then invent a short, friendly, memorable pet-style name for it (one or two words, not the plant type itself).
Names already taken, which you must not reuse: {taken}
If the evidence does not show what kind of plant it is, set species to null.
Reply with ONLY JSON: {{"species": "Jade plant" or null, "name": "Jasper" or null}}

EVIDENCE:
{evidence}"""


def _evidence(plant_id, cid):
    parts = []
    last = db.rows("SELECT analysis FROM entries WHERE plant_id=? AND kind='check-up' ORDER BY id DESC LIMIT 1", (plant_id,))
    if last and last[0]["analysis"]:
        try:
            pl = (json.loads(last[0]["analysis"]).get("plant") or {})
            if pl.get("name"): parts.append(f"Photo check-up says the plant looks like: {pl['name']} ({pl.get('confidence', '?')} confidence)")
        except ValueError: pass
    if cid:
        msgs = db.rows("SELECT role,content FROM messages WHERE conversation_id=? AND content!='' ORDER BY id LIMIT 8", (cid,))
        parts.append("\n".join(f"{m['role']}: {m['content'][:300]}" for m in msgs))
    return "\n".join(p for p in parts if p.strip())


def _unique(name, taken):
    base, n = name, 2
    while name.lower() in taken: name, n = f"{base} {n}", n + 1
    return name


def name_plant(plant_id, cid=0, force=False):
    """Returns the new name, or None if the plant already has a real name or the evidence is not enough yet."""
    p = (db.rows("SELECT name,species FROM plants WHERE id=?", (plant_id,)) or [None])[0]
    if not p or (not force and p["name"].strip().lower() not in PLACEHOLDERS): return None
    ev = _evidence(plant_id, cid)
    if not ev: return None
    taken = {r["name"].lower() for r in db.rows("SELECT name FROM plants WHERE id!=?", (plant_id,))}
    with trace.span("tool", "Name the plant") as a:
        from src.remote_vlm import RemoteVLM
        try:
            raw = RemoteVLM().chat([{"role": "user", "content": PROMPT.format(taken=", ".join(sorted(taken)) or "none", evidence=ev)}], 80, 0.9, "Name the plant")
            d = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except Exception as e:
            a["error"] = str(e)[:120]; return None
        species, pet = (d.get("species") or "").strip(), re.sub(r"[^\w' -]", "", d.get("name") or "").strip()[:30]
        if not species or not pet: a["decided"] = "not enough evidence"; return None
        name = _unique(f"{pet} the {species}", taken)
        db.run("UPDATE plants SET name=?, species=COALESCE(NULLIF(species,''),?) WHERE id=?", (name, species, plant_id))
        a["name"] = name
        return name


@router.post("/{pid}/auto-name")
def auto_name(pid: int, body: dict = None):
    """Ask the model to (re)name this plant. {"force": true} renames even if it already has a real name."""
    return {"name": name_plant(pid, (body or {}).get("conversation_id", 0), bool((body or {}).get("force")))}
