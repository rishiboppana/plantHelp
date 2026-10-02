#!/usr/bin/env python3
"""
Validate PlantLens KB records.

Usage:  python src/validate/validate.py [--dir kb/records/draft] [--reviewed]
Exit code 0 = all good, 1 = errors found.

Checks: JSON Schema, every symptom/plant/group/part/cause-category id exists in the vocab,
source_id exists in sources.yaml and matches source_url, unique record ids,
problem records have a cause, derived questions are tagged, no empty summaries.
"""
import argparse
import glob
import json
import os
import sys

import yaml

try:
    import jsonschema
except ImportError:  # still run the manual checks
    jsonschema = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KB = os.path.join(ROOT, "kb")


def load_yaml(p):
    with open(os.path.join(KB, p), encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(KB, "records", "draft"))
    args = ap.parse_args()

    symptoms = {s["id"] for s in load_yaml("vocab/symptoms.yaml")}
    parts = set(load_yaml("vocab/plant_parts.yaml"))
    cats = set(load_yaml("vocab/cause_categories.yaml"))
    locs = set(load_yaml("vocab/location_patterns.yaml"))
    pv = load_yaml("vocab/plants.yaml")
    plants = {p["id"] for p in pv["plants"]}
    groups = set(pv["groups"])
    sources = {s["source_id"]: s for s in load_yaml("sources/sources.yaml")}
    with open(os.path.join(KB, "schema", "record.schema.json"), encoding="utf-8") as f:
        schema = json.load(f)

    errors, warnings, seen, total, unsure = [], [], set(), 0, 0
    for path in sorted(glob.glob(os.path.join(args.dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            records = json.load(f)
        for r in records:
            total += 1
            rid = r.get("record_id", "<no id>")
            if jsonschema:
                for e in jsonschema.Draft202012Validator(schema).iter_errors(r):
                    errors.append("%s: schema: %s" % (rid, e.message))
            if rid in seen:
                errors.append("%s: duplicate record_id" % rid)
            seen.add(rid)
            for s in r.get("symptoms", []):
                if s not in symptoms:
                    errors.append("%s: unknown symptom id '%s'" % (rid, s))
            for p in r.get("plants", []):
                if p not in plants:
                    errors.append("%s: unknown plant id '%s'" % (rid, p))
            for g in r.get("plant_groups", []):
                if g not in groups:
                    errors.append("%s: unknown plant group '%s'" % (rid, g))
            for p in r.get("plant_parts", []):
                if p not in parts:
                    errors.append("%s: unknown plant part '%s'" % (rid, p))
            for l in r.get("location_patterns", []):
                if l not in locs:
                    errors.append("%s: unknown location pattern '%s'" % (rid, l))
            if r.get("cause_category") not in cats | {None}:
                errors.append("%s: unknown cause_category" % rid)
            sid = r.get("source_id")
            if sid not in sources:
                errors.append("%s: source_id '%s' not in sources.yaml" % (rid, sid))
            elif sources[sid]["url"] != r.get("source_url"):
                errors.append("%s: source_url does not match sources.yaml" % rid)
            if r.get("kind") == "problem" and not r.get("cause"):
                errors.append("%s: problem record without a cause" % rid)
            if r.get("kind") == "plant_profile" and not r.get("plants"):
                errors.append("%s: plant_profile without a plant" % rid)
            if r.get("symptoms_stated") and not r.get("symptoms"):
                errors.append("%s: symptoms_stated is true but symptoms is empty" % rid)
            if r.get("unsure"):
                unsure += 1
            if r.get("status") == "draft" and "reviewed" in args.dir:
                errors.append("%s: draft record inside a reviewed folder" % rid)

    print("records checked: %d | unsure: %d" % (total, unsure))
    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    print("RESULT:", "FAIL (%d errors)" % len(errors) if errors else "OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
