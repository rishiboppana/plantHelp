"""NeMo Guardrails for PlantLens: the user's message is checked before the pipeline runs, the reply before it is shown.
Rails (config in guardrails/): regex rails (free, instant) then a self-check call to the same Hugging Face model.
Fails open: if the guard itself breaks (network, config), the message passes and the trace says so. PLANTLENS_GUARDRAILS=off disables it."""
import asyncio, os, threading
from pathlib import Path
from src import trace
from src.remote_vlm import RemoteVLM

CONFIG = Path(__file__).resolve().parents[1] / "guardrails"
ENABLED = os.environ.get("PLANTLENS_GUARDRAILS", "on").lower() not in ("off", "0", "false")
REFUSE_IN = "I can only help with plant questions, and I can't help with that request. Send a photo or ask me about your plant."
REFUSE_OUT = "I can't share that answer. For chemical treatments or doses, check the product label or ask a local nursery; for a pet or person who may have eaten a plant, call a vet or poison control."


class _Model:
    """Presents RemoteVLM as the NeMo LLMModel protocol. The call is made inline (not in an executor) so the trace span stays on this thread."""
    provider_name, provider_url = "huggingface", None

    def __init__(self, vlm): self.vlm = vlm

    @property
    def model_name(self): return self.vlm.models[0]

    async def generate_async(self, prompt, *, stop=None, **kw):
        from nemoguardrails.types import LLMResponse
        msgs = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else \
               [{"role": m.role.value, "content": m.content} for m in prompt]
        return LLMResponse(content=self.vlm.chat(msgs, 10, 0.0, "Guardrail check"), model=self.model_name)

    async def stream_async(self, prompt, *, stop=None, **kw):
        from nemoguardrails.types import LLMResponseChunk
        yield LLMResponseChunk(delta_content=(await self.generate_async(prompt)).content)


class Guard:
    def __init__(self, vlm=None):
        self._vlm, self._rails, self._lock = vlm, None, threading.Lock()

    def _load(self):
        with self._lock:
            if self._rails is None:
                from nemoguardrails import LLMRails, RailsConfig
                self._rails = LLMRails(RailsConfig.from_path(str(CONFIG)), llm=_Model(self._vlm or RemoteVLM()))
            return self._rails

    def _check(self, kind, text):
        """kind: 'input' | 'output'. Returns (allowed, rail_name_or_None)."""
        if not ENABLED or not (text or "").strip(): return True, None
        label = f"Guardrails ({kind})"
        with trace.span("tool", label) as a:
            try:
                from nemoguardrails.rails.llm.options import RailType
                rails = self._load()
                msgs = [{"role": "user", "content": text}] if kind == "input" else \
                       [{"role": "user", "content": "(user message)"}, {"role": "assistant", "content": text}]
                res = asyncio.run(rails.check_async(msgs, rail_types=[RailType(kind)]))
            except Exception as e:
                a.update(status="error_fail_open", error=str(e)[:200])
                return True, None
            a.update(status=res.status.value, rail=res.rail)
            return res.status.value != "blocked", res.rail

    def check_input(self, text): return self._check("input", text)
    def check_output(self, text): return self._check("output", text)


guard = Guard()
