"""Conversation memory graph. When a chat fills 85% of the model's context window, the conversation is condensed into this graph
(plant, symptoms, causes, actions, what the user said, what was advised, open questions, each linked to what it relates to).
From then on a prompt carries only the part of the graph that matches the new message instead of the whole transcript.
The graph is plain JSON, saved with the conversation's state; retrieval is lexical match + one hop of neighbours."""
import re
from math import log
from src.trace import tok

TYPES = ("plant", "symptom", "cause", "action", "fact", "advice", "question")
_STOP = set("the a an and or but if is are was were be been to of in on at for with it its this that these those my your i you we me "
            "do does did can could should would will what why how when where which who not no yes so as by from there their than then "
            "have has had just very really about again still also any some more".split())


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2 and w not in _STOP}


def _stem(w): return w[:-1] if len(w) > 4 and w.endswith("s") else w


def _terms(s): return {_stem(w) for w in _words(s)}


class ConvGraph:
    def __init__(self, nodes=None, edges=None, built_turn=0):
        self.nodes, self.edges, self.built_turn = nodes or {}, edges or [], built_turn

    def to_dict(self): return {"nodes": self.nodes, "edges": self.edges, "built_turn": self.built_turn}

    @classmethod
    def from_dict(cls, d): return cls(d.get("nodes"), d.get("edges"), d.get("built_turn", 0))

    def add_node(self, type, text, turn=0):
        text = " ".join((text or "").split())[:300]
        if not text: return None
        type = type if type in TYPES else "fact"
        key = (type, text.lower())
        for n in self.nodes.values():
            if (n["type"], n["text"].lower()) == key: return n["id"]
        nid = f"n{len(self.nodes) + 1}"
        self.nodes[nid] = {"id": nid, "type": type, "text": text, "turn": turn}
        return nid

    def add_edge(self, s, t, rel="related"):
        if s and t and s != t and s in self.nodes and t in self.nodes and not any(e["s"] == s and e["t"] == t and e["rel"] == rel for e in self.edges):
            self.edges.append({"s": s, "t": t, "rel": (rel or "related")[:40]})

    # ---- building ----
    def seed_from_state(self, observation, records, turn=0):
        """Structured facts the app already holds: no model call needed for these."""
        o = observation or {}
        pl = o.get("plant") or {}
        plant = self.add_node("plant", f"{pl['name']} (confidence {pl.get('confidence', '?')})", turn) if pl.get("name") else None
        syms = [self.add_node("symptom", s.replace("_", " "), turn) for s in o.get("symptoms") or []]
        for s in syms: self.add_edge(plant, s, "shows")
        for r in records or []:
            c = self.add_node("cause", f"{r['cause']} ({r.get('category') or r.get('cause_category', '')})", turn)
            for s in syms: self.add_edge(c, s, "may explain")
            for a in (r.get("next_actions") or [])[:3]:
                self.add_edge(self.add_node("action", a, turn), c, "addresses")

    def merge_extracted(self, data, turn=0):
        """Add what the model pulled out of the transcript: {"nodes": [{id,type,text,turn}], "edges": [{from,to,rel}]}."""
        ids = {}
        for n in (data.get("nodes") or [])[:60]:
            if isinstance(n, dict) and n.get("text"):
                t = n.get("turn")
                ids[str(n.get("id"))] = self.add_node(n.get("type"), str(n["text"]), t if isinstance(t, int) else turn)
        for e in (data.get("edges") or [])[:120]:
            if isinstance(e, dict): self.add_edge(ids.get(str(e.get("from"))), ids.get(str(e.get("to"))), str(e.get("rel") or "related"))

    def add_exchange(self, turn, user_text, reply):
        """Keep the graph growing after it takes over: one node for what the user said, one for the answer's bottom line."""
        u = self.add_node("fact", f"User said: {user_text}", turn) if (user_text or "").strip() else None
        bottom = (reply or "").split("\n---")[0].strip()
        a = self.add_node("advice", f"Told the user: {bottom}", turn) if bottom else None
        self.add_edge(a, u, "replies to")
        words = _terms(user_text) | _terms(bottom)
        for n in list(self.nodes.values()):                       # link to the entities this exchange talks about
            if n["type"] in ("plant", "symptom", "cause") and _terms(n["text"]) & words:
                self.add_edge(u, n["id"], "about"); self.add_edge(a, n["id"], "about")

    # ---- retrieval ----
    def retrieve(self, query, budget=900, limit_seeds=6):
        """-> (text for the prompt, [node ids used]). Seeds = nodes matching the query; plus the plant and its symptoms, the latest
        exchange when the message is short or matches nothing ('should I remove it?'), and one hop of neighbours."""
        if not self.nodes: return "", []
        q = _terms(query)
        df = {}
        for n in self.nodes.values():
            for t in _terms(n["text"]): df[t] = df.get(t, 0) + 1
        N = len(self.nodes)
        score = {i: sum(log(1 + N / df[t]) for t in q & _terms(n["text"])) for i, n in self.nodes.items()}
        seeds = [i for i, s in sorted(score.items(), key=lambda x: -x[1]) if s > 0][:limit_seeds]
        last = max(n["turn"] for n in self.nodes.values())
        core = [i for i, n in self.nodes.items() if n["type"] in ("plant", "symptom")]
        recent = [i for i, n in self.nodes.items() if n["turn"] == last and n["type"] in ("fact", "advice", "question")] if (len(q) <= 3 or not seeds) else []
        near = []
        for e in self.edges:
            if e["s"] in seeds and e["t"] not in seeds: near.append(e["t"])
            if e["t"] in seeds and e["s"] not in seeds: near.append(e["s"])
        picked, used = [], 0
        for i in dict.fromkeys(seeds + core + recent + near):
            cost = tok(self.nodes[i]["text"]) + 4
            if used + cost > budget: continue
            picked.append(i); used += cost
        keep = set(picked)
        lines = [f"- ({self.nodes[i]['type']}) {self.nodes[i]['text']}" for i in picked]
        lines += [f"- {self.nodes[e['s']]['text'][:60]} --{e['rel']}--> {self.nodes[e['t']]['text'][:60]}" for e in self.edges if e["s"] in keep and e["t"] in keep][:12]
        return "\n".join(lines), picked


EXTRACT = """You condense a plant-care conversation into a memory graph so it can be dropped from the prompt and looked up later.
Output ONLY JSON: {"nodes": [{"id": "a", "type": "...", "text": "...", "turn": 1}], "edges": [{"from": "a", "to": "b", "rel": "..."}]}
Node types: plant (which plant, where it lives), symptom (what was seen or reported), cause (a possible cause discussed), action (something the user did or was told to do, with dates), fact (anything the user stated: habits, light, watering, changes, preferences), advice (a recommendation or conclusion the assistant gave), question (something still unanswered).
Keep numbers, dates and the user's own wording. Short texts (under 25 words). At most 40 nodes. Link each node to what it relates to (rel: shows, caused by, tried for, answers, contradicts, follows).
Do not invent anything that is not in the conversation."""
