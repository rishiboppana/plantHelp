import os
os.environ.setdefault("PLANTLENS_GUARDRAILS", "off")   # offline tests must not call the guard model; test_guardrails turns it back on
