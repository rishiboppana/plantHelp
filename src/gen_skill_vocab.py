"""Regenerate plantlens/references/symptoms.md from kb/vocab so the model and the index share one vocabulary.
Usage: python -m src.gen_skill_vocab"""
import yaml
from pathlib import Path
from src.validate.validate import KB

OUT = KB.parent / "plantlens" / "references" / "symptoms.md"
v = lambda f: yaml.safe_load((KB / "vocab" / f).read_text())
sym, loc, parts = v("symptoms.yaml"), v("plant_parts.yaml")["plant_parts"], None
def lay(s):
    return ", ".join('"%s"' % x for x in s["synonyms"][:3])


rows = "\n".join("| `%s` | %s | %s |" % (s["id"], s["label"], lay(s)) for s in sym["symptoms"] if s["id"] != "healthy")
OUT.write_text(f"""# Symptom vocabulary

GENERATED from `kb/vocab/symptoms.yaml` by `python -m src.gen_skill_vocab`. Do not edit by hand; edit the yaml and regenerate. The knowledge base uses the same ids, which is what makes retrieval work.

## Plant parts
{', '.join(f"`{p['id']}`" for p in v('plant_parts.yaml')['plant_parts'])}

## Symptoms

| id | What it looks like | Lay wording users may use |
|---|---|---|
{rows}

## Location patterns
{', '.join(f"`{p['id']}`" for p in sym['location_patterns'])}

## Extent
`few_leaves`, `many_leaves`, `whole_plant`

## Other visible clues (use as `other_visible`)
`soil_looks_wet`, `soil_looks_dry`, `soil_crusted`, `pot_no_drainage`, `webbing`, `insects_visible`, `dust_on_leaves`, `direct_sun_exposure`

## Rules for describing
- Use the closest id. If nothing fits, describe it in plain words in `other_visible` instead of inventing an id.
- Use mold-like growth or white powdery coating, not a disease name. A photo shows the appearance, not the pathogen.
- Report only what is visible. Do not infer watering or light from the photo unless the soil, pot, or light is actually shown.
""")
print("wrote", OUT)
