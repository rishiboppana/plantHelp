"""Progress comparison, recovery plan and 'why' explanations. All pure functions over saved check-up cards
(the dicts built by backend.main.analysis_from), so the trend and the plan are decided by code, not by model memory.
The optional photo-vs-photo note is the only model call, and it only adds one sentence."""
RANK = {"green": 0, "yellow": 1, "red": 2}
ICON = {"improving": "📈", "worsening": "📉", "unchanged": "➖", "changing": "🔄"}


def compare_cards(prev, new):
    """Trend between two check-up cards: symptoms resolved / new / persisting plus the change in urgency."""
    ps, ns = set(prev.get("symptoms", [])), set(new.get("symptoms", []))
    resolved, appeared, kept = sorted(ps - ns), sorted(ns - ps), sorted(ps & ns)
    d = RANK.get(new.get("urgency"), 0) - RANK.get(prev.get("urgency"), 0)
    if d < 0 or (d == 0 and len(resolved) > len(appeared)): trend = "improving"
    elif d > 0 or (d == 0 and len(appeared) > len(resolved)): trend = "worsening"
    else: trend = "unchanged" if ps == ns else "changing"
    parts = []
    if resolved: parts.append("no longer visible: " + ", ".join(resolved))
    if appeared: parts.append("new: " + ", ".join(appeared))
    if kept: parts.append("still there: " + ", ".join(kept))
    if d: parts.append(f"urgency went {prev.get('urgency', 'green')} → {new.get('urgency', 'green')}")
    head = {"improving": "Looks better than last time", "worsening": "Looks worse than last time",
            "unchanged": "No visible change since last time", "changing": "Different symptoms from last time"}[trend]
    return {"stub": False, "trend": trend, "icon": ICON[trend], "resolved": resolved, "new": appeared, "persisting": kept,
            "urgency": {"before": prev.get("urgency", "green"), "after": new.get("urgency", "green")},
            "summary": head + (" (" + "; ".join(parts) + ")." if parts else ".")}


def visual_note(vlm, before_path, after_path):
    """One sentence comparing the two photos directly. Best effort: any failure returns None."""
    try:
        msg = [{"role": "user", "content": [
            {"type": "image_path", "path": before_path}, {"type": "image_path", "path": after_path},
            {"type": "text", "text": "The first photo is the plant earlier, the second is the same plant now. In ONE short sentence, say whether the affected areas "
                                     "look better, worse or about the same, and what changed. Do not name a disease."}]}]
        out = (vlm.chat(msg, 80, 0.0, "Compare photos") or "").strip().split("\n")[0]
        return out or None
    except Exception:
        return None


def build_plan(card, recheck_days=2):
    """Today / next few days / next week, taken from the card's checklist (which itself comes from retrieved KB records)."""
    steps = [s for s in card.get("checklist", []) if not s.lower().startswith("re-check")]
    if card.get("urgency") == "green" or not card.get("possibilities"):
        return {"stub": False, "today": ["Nothing urgent. Keep your usual care routine."], "next_days": steps[:2],
                "next_week": ["Upload a new photo to compare"]}
    return {"stub": False, "today": steps[:2] or ["Look closely at the leaf undersides and the soil"],
            "next_days": steps[2:5] + [f"Re-check with a new photo in {recheck_days} day{'s' if recheck_days != 1 else ''}"],
            "next_week": ["Upload a new photo to compare with this one", "If it is getting worse, ask about the optional questions first"]}


def explain_card(card, profile=None, cause=None):
    """Connect each suggestion to the observed symptoms, the record it came from and the saved plant context."""
    refs = {r["title"]: r for r in card.get("references", [])}
    items = []
    for p in card.get("possibilities", []):
        if cause and cause.lower() not in p["cause"].lower(): continue
        r = refs.get(p["cause"], {})
        items.append({"cause": p["cause"], "likelihood": p["likelihood"], "because": r.get("snippet", ""), "source": r.get("url", "")})
    ctx = [f"{k}: {v}" for k, v in (profile or {}).items() if v]
    seen = ", ".join(card.get("symptoms", [])) or "no clear symptoms"
    text = f"I saw {seen}. " + ("These causes match what I saw: " + "; ".join(i["cause"] for i in items) + "." if items else "I have no matching cause in my knowledge base.")
    if ctx: text += " Your saved context (" + "; ".join(ctx[:4]) + ") also shaped the advice."
    return {"stub": False, "explanation": text, "items": items}
