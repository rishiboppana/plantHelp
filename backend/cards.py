"""Card summaries: one profile card per plant and one summary card per chat, built from what is already saved (no model call)."""
import json
from datetime import date
from fastapi import APIRouter
import db

router = APIRouter(prefix="/api/cards", tags=["cards"])
CARE_KEYS = ("light", "watering", "location", "soil", "indoor/outdoor", "temperature", "humidity")


def _json(s):
    try: return json.loads(s) if s else {}
    except ValueError: return {}


@router.get("/plants")
def plant_cards():
    today = date.today().isoformat(); out = []
    for p in db.rows("SELECT * FROM plants ORDER BY id"):
        pid, profile = p["id"], {k: v for k, v in _json(p["profile"]).items() if v}
        last = db.rows("SELECT analysis,image,created FROM entries WHERE plant_id=? AND kind='check-up' ORDER BY id DESC LIMIT 1", (pid,))
        a = _json(last[0]["analysis"]) if last else {}
        photo = db.rows("SELECT image FROM entries WHERE plant_id=? AND image IS NOT NULL ORDER BY id DESC LIMIT 1", (pid,))
        nxt = db.rows("SELECT title,due FROM events WHERE plant_id=? AND status='planned' AND due IS NOT NULL ORDER BY due LIMIT 1", (pid,))
        n = lambda sql: db.rows(sql, (pid,))[0]["n"]
        out.append({
            "id": pid, "name": p["name"], "species": p["species"] or profile.get("species", ""), "status": p["status"], "since": (p["created"] or "")[:10],
            "photo": photo[0]["image"] if photo else None,
            "care": {k: profile[k] for k in CARE_KEYS if k in profile},
            "condition": {"checked": last[0]["created"][:10] if last else None, "symptoms": a.get("symptoms", []),
                          "possible_causes": [x["cause"] for x in a.get("possibilities", [])][:3]},
            "next": {**nxt[0], "overdue": nxt[0]["due"] < today} if nxt else None,
            "counts": {"checkups": n("SELECT COUNT(*) n FROM entries WHERE plant_id=? AND kind='check-up'"),
                       "chats": n("SELECT COUNT(*) n FROM conversations WHERE plant_id=?"),
                       "done": n("SELECT COUNT(*) n FROM events WHERE plant_id=? AND status='done'"),
                       "open": n("SELECT COUNT(*) n FROM events WHERE plant_id=? AND status='planned'")},
        })
    return out


@router.get("/chats")
def chat_cards():
    out = []
    for c in db.rows("SELECT c.id,c.title,c.updated,c.plant_id,p.name AS plant FROM conversations c LEFT JOIN plants p ON p.id=c.plant_id ORDER BY c.updated DESC, c.id DESC"):
        msgs = db.rows("SELECT role,content,image,analysis FROM messages WHERE conversation_id=? ORDER BY id", (c["id"],))
        cards = [_json(m["analysis"]) for m in msgs if m["analysis"]]
        said = [m["content"] for m in msgs if m["role"] == "assistant" and m["content"]]
        asked = [m["content"] for m in msgs if m["role"] == "user" and m["content"]]
        photo = next((m["image"] for m in reversed(msgs) if m["image"]), None)
        card = cards[-1] if cards else {}
        out.append({**c, "messages": len(msgs), "photo": photo, "status": card.get("urgency"),
                    "symptoms": card.get("symptoms", [])[:4], "asked": (asked[0] if asked else "")[:140],
                    "gist": (said[-1].split("\n---\n")[0] if said else "")[:220]})
    return out
