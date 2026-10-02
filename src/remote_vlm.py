"""Client for Qwen3-VL via the Hugging Face router (OpenAI-compatible). Reads HF_TOKEN from the environment; never hardcode it.
Smoke test: HF_TOKEN=... python -m src.remote_vlm --photo path/to/leaf.jpg [--text "What's wrong with my plant?"]
"""
import argparse, base64, json, mimetypes, os, ssl, threading, urllib.error, urllib.request
from src.trace import span, tok
from src.limits import context_limit

try:  # python.org builds on macOS ship without root certs; use certifi's bundle when available
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = None

def _load_env():
    """Load KEY=VALUE lines from .env (repo root or src/) without overriding real environment variables."""
    for d in (os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        path = os.path.join(d, ".env")
        if os.path.exists(path):
            for line in open(path):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_env()
BASE_URL = os.environ.get("PLANTLENS_BASE_URL", "https://router.huggingface.co/v1")
# Tried in order; the next is used when a provider is at capacity (503/429). ":provider" picks the serving provider.
MODELS = [m for m in os.environ.get("PLANTLENS_MODEL", "").split(",") if m] or [
    "Qwen/Qwen3-VL-30B-A3B-Instruct:novita", "Qwen/Qwen3-VL-30B-A3B-Instruct:deepinfra", "Qwen/Qwen3-VL-8B-Instruct:featherless-ai"]


def _data_url(path):
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


class RemoteVLM:
    def __init__(self, model=None, base_url=None, token=None, timeout=300):
        self.models = [model] if model else MODELS
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.token = token or os.environ.get("HF_TOKEN")
        local = any(h in self.base_url for h in ("localhost", "127.0.0.1"))
        if not self.token and not local:
            raise RuntimeError("set the HF_TOKEN environment variable (or point PLANTLENS_BASE_URL at a local server)")
        self.token = self.token or "local"
        self.timeout = timeout
        self._tl = threading.local()
        self.on_usage = None       # optional callback(label, usage) after every successful call (the session's context ledger)

    @property
    def last_usage(self):
        """Token usage of the most recent call on this thread: {prompt_tokens, completion_tokens, total_tokens, source}."""
        return getattr(self._tl, "usage", None)

    def _prepare(self, messages):
        """Wire format for the API plus the image count and a prompt-token estimate (used when the provider reports no usage)."""
        wire = []
        for m in messages:
            if isinstance(m["content"], str):
                wire.append(m); continue
            parts = []
            for c in m["content"]:
                if c["type"] == "image_path":
                    parts.append({"type": "image_url", "image_url": {"url": _data_url(c["path"])}})
                elif c["type"] == "image_url":
                    parts.append({"type": "image_url", "image_url": {"url": c["url"]}})
                else:
                    parts.append(c)
            wire.append({"role": m["role"], "content": parts})
        images = sum(1 for m in messages if not isinstance(m["content"], str) for c in m["content"] if c["type"] != "text")
        est_prompt = sum(tok(m["content"] if isinstance(m["content"], str) else
                             " ".join(c.get("text", "") for c in m["content"] if c["type"] == "text")) for m in messages) + 576 * images
        return wire, images, est_prompt

    def _record_usage(self, a, model, label, u, out, est_prompt, tried):
        pt, ct = u.get("prompt_tokens"), u.get("completion_tokens")
        source = "provider" if pt is not None and ct is not None else "estimate"
        pt, ct = (pt, ct) if source == "provider" else (est_prompt, tok(out))
        limit, lsrc = context_limit(model, self.base_url, _SSL)
        self._tl.usage = {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct, "source": source,
                          "model": model, "limit": limit, "limit_source": lsrc}
        a.update(self._tl.usage, failed_providers=tried)
        if self.on_usage: self.on_usage(label, self._tl.usage)

    def stream_chat(self, messages, max_new_tokens=700, temperature=0.3, label="Model call", on_delta=None):
        """Like chat(), but calls on_delta(text) for every piece of the reply as it arrives (server-sent events). Returns the full text.
        Falls through to the next provider only while nothing has been emitted; a failure mid-stream raises."""
        wire, images, est_prompt = self._prepare(messages)
        err, tried, self._tl.usage = None, [], None
        with span("model", label, max_tokens=max_new_tokens, images=images, streamed=True) as a:
            for model in self.models:
                body = {"model": model, "messages": wire, "max_tokens": max_new_tokens, "temperature": temperature,
                        "stream": True, "stream_options": {"include_usage": True}}
                req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}", "User-Agent": "plantlens/0.1"})
                out, usage, started = [], {}, False
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL) as r:
                        if "event-stream" not in (r.headers.get("Content-Type") or ""):     # provider ignored stream=true: one JSON body
                            data = json.load(r)
                            text = data["choices"][0]["message"]["content"].strip()
                            usage = data.get("usage") or {}
                            if on_delta and text: on_delta(text)
                            out = [text]
                        else:
                            for raw in r:
                                line = raw.decode("utf-8", "replace").strip()
                                if not line.startswith("data:"): continue
                                chunk = line[5:].strip()
                                if chunk == "[DONE]": break
                                ev = json.loads(chunk)
                                usage = ev.get("usage") or usage
                                for ch in ev.get("choices") or []:
                                    d = (ch.get("delta") or {}).get("content")
                                    if d:
                                        started = True; out.append(d)
                                        if on_delta: on_delta(d)
                    text = "".join(out).strip()
                    self._record_usage(a, model, label, usage, text, est_prompt, tried)
                    return text
                except urllib.error.HTTPError as e:
                    err = f"{model}: router returned {e.code}: {e.read().decode()[:200]}"
                    tried.append({"model": model, "code": e.code})
                    if e.code not in (429, 502, 503): break
                except Exception as e:
                    if started: raise                      # tokens already reached the user; cannot restart on another provider
                    err = f"{model}: {e}"; tried.append({"model": model, "error": str(e)[:80]})
            a["failed_providers"] = tried
            raise RuntimeError(err) from None

    def chat(self, messages, max_new_tokens=700, temperature=0.3, label="Model call"):
        """messages: [{role, content: str | [{type:'text',text} | {type:'image_path',path} | {type:'image_url',url}]}]"""
        wire, images, est_prompt = self._prepare(messages)
        err, tried, self._tl.usage = None, [], None
        with span("model", label, max_tokens=max_new_tokens, images=images) as a:
            for model in self.models:
                body = {"model": model, "messages": wire, "max_tokens": max_new_tokens, "temperature": temperature}
                req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}", "User-Agent": "plantlens/0.1"})
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL) as r:
                        data = json.load(r)
                    out = data["choices"][0]["message"]["content"].strip()
                    self._record_usage(a, model, label, data.get("usage") or {}, out, est_prompt, tried)
                    return out
                except urllib.error.HTTPError as e:
                    err = f"{model}: router returned {e.code}: {e.read().decode()[:200]}"
                    tried.append({"model": model, "code": e.code})
                    if e.code not in (429, 502, 503): break
            a["failed_providers"] = tried
            raise RuntimeError(err) from None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--photo"); ap.add_argument("--text", default="Describe what you see.")
    a = ap.parse_args()
    content = ([{"type": "image_path", "path": a.photo}] if a.photo else []) + [{"type": "text", "text": a.text}]
    print(RemoteVLM().chat([{"role": "user", "content": content}], 300))
