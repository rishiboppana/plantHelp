"""Validate KB records: schema, vocab ids, source ids. Usage: python -m src.validate.validate [dir_or_file ...]"""
import json, sys
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator

KB = Path(__file__).resolve().parents[2] / "kb"


def _ids(path, key):
    return {x["id"] for x in yaml.safe_load((KB / "vocab" / path).read_text())[key]}


def load_vocab():
    return {
        "symptoms": _ids("symptoms.yaml", "symptoms"),
        "location_patterns": _ids("symptoms.yaml", "location_patterns"),
        "plant_parts": _ids("plant_parts.yaml", "plant_parts"),
        "cause_category": _ids("cause_categories.yaml", "cause_categories"),
        "plants": _ids("plants.yaml", "plants"),
        "plant_groups": set(yaml.safe_load((KB / "vocab" / "plants.yaml").read_text())["groups"]),
        "sources": {s["source_id"] for s in yaml.safe_load((KB / "sources" / "sources.yaml").read_text())["sources"]},
    }


def validate_record(rec, vocab, validator):
    errs = [f"schema: {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in validator.iter_errors(rec)]
    for field in ("symptoms", "location_patterns", "plant_parts", "plants", "plant_groups"):
        for v in rec.get(field, []):
            if v not in vocab[field]:
                errs.append(f"vocab: unknown {field} id '{v}'")
    if rec.get("cause_category") not in vocab["cause_category"]:
        errs.append(f"vocab: unknown cause_category '{rec.get('cause_category')}'")
    if rec.get("source_id") not in vocab["sources"]:
        errs.append(f"source: unknown source_id '{rec.get('source_id')}'")
    return errs


def iter_records(paths):
    for p in paths:
        p = Path(p)
        for f in sorted(p.rglob("*.json*")) if p.is_dir() else [p]:
            if f.suffix == ".jsonl":
                for i, line in enumerate(f.read_text().splitlines()):
                    if line.strip():
                        yield f"{f}:{i+1}", json.loads(line)
            elif f.suffix == ".json":
                data = json.loads(f.read_text())
                for i, r in enumerate(data if isinstance(data, list) else [data]):
                    yield f"{f}[{i}]", r


def main(argv):
    paths = argv or [KB / "records" / "draft", KB / "records" / "reviewed"]
    vocab = load_vocab()
    validator = Draft202012Validator(json.loads((KB / "schema" / "record.schema.json").read_text()))
    n = bad = 0
    seen = set()
    for where, rec in (r for p in paths for r in (seen.clear() or iter_records([p]))):  # ids may repeat across draft/ and reviewed/, not within one
        n += 1
        errs = validate_record(rec, vocab, validator)
        if rec.get("record_id") in seen:
            errs.append(f"duplicate record_id {rec.get('record_id')}")
        seen.add(rec.get("record_id"))
        if errs:
            bad += 1
            print(f"FAIL {where}")
            for e in errs:
                print("   ", e)
    print(f"{n} records, {n-bad} ok, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
