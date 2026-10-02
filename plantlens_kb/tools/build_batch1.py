#!/usr/bin/env python3
"""
Builds the batch-1 knowledge-base files for PlantLens:
  kb/vocab/*.yaml, kb/sources/sources.yaml, kb/schema/record.schema.json,
  kb/records/draft/records_batch1.json, kb/review/review_batch1.csv

RULES THAT APPLY TO EVERY RECORD (also for batch 2):
  * Extract only what the source page states, in our own words. No outside knowledge.
  * If the page is silent on a field, leave it empty (symptoms_stated=False when the
    page gives no symptoms).
  * Questions/inspection items the page does not literally state are allowed only when
    they follow directly from the stated cause, and are tagged basis="derived_from_cause"
    so the human reviewer can see them.
  * Set unsure=True when the page is ambiguous, thin, or two reads of it disagreed.
  * Every record carries source_id and source_url.

Use this file as the template for batch 2: add data below, rerun, then run
src/validate/validate.py.
"""
import csv
import json
import os

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
KB = os.path.join(os.path.dirname(HERE), "kb")


def out(path, text):
    full = os.path.join(KB, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def dump_yaml(path, data):
    out(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


# ----------------------------------------------------------------- vocabulary
SYMPTOMS = [
    ("yellowing", "Yellowing", "yellow leaves; pale leaves; chlorosis"),
    ("brown_spots", "Brown spots", "brown dots; spotty leaves; leaf spots"),
    ("black_spots", "Black spots", "black patches; dark spots"),
    ("brown_tips_edges", "Brown tips or edges", "crispy tips; burnt edges; tip dieback"),
    ("dry_brown_patch", "Large dry brown patch", "big brown dead area; crispy patch; dead patch on leaf"),
    ("curling", "Curling", "curled leaves; cupped leaves"),
    ("wilting_drooping", "Wilting or drooping", "droopy; wilted; limp"),
    ("holes_chewed", "Holes or chewed edges", "leaves eaten; bitten"),
    ("stippling", "Stippling", "speckled leaves; tiny pale dots; dusty look"),
    ("white_powdery_coating", "White powdery coating", "white dust; powdery film"),
    ("fuzzy_mold_growth", "Fuzzy or mold-like growth", "mold; fuzz"),
    ("sticky_residue", "Sticky residue", "sticky leaves; shiny film"),
    ("webbing", "Webbing", "cobwebs; fine webs"),
    ("visible_insects", "Visible insects", "bugs; white fluff; cottony bits"),
    ("leaf_drop", "Leaf drop", "dropping leaves; leaves falling off"),
    ("stunted_growth", "Stunted growth", "not growing; weak growth; poor growth"),
    ("leggy_stretched", "Leggy or stretched", "spindly; reaching; long gaps between leaves"),
    ("soft_mushy_stem", "Soft or mushy stem", "rotting; dark soft base"),
    ("faded_color", "Faded color", "losing color; washed-out; pale"),
    ("distorted_growth", "Distorted growth", "twisted or misshapen leaves or flowers"),
    ("scorched_leaves", "Scorched leaves", "sun-burned; bleached or burnt patches"),
    ("small_leaves", "Small leaves", "undersized leaves"),
]
PLANT_PARTS = ["leaf", "stem", "fruit", "flower", "whole_plant", "roots", "soil"]
CAUSE_CATEGORIES = ["watering", "nutrient", "pest", "disease", "environment"]
LOCATION_PATTERNS = [
    "lower_leaves_first", "new_growth_first", "leaf_edges",
    "between_veins", "one_side_only", "whole_plant", "scattered",
]
PLANTS = {
    "jade": ("Jade plant", ["jade plant", "Crassula ovata"], ["succulent", "houseplant"]),
    "pothos": ("Pothos", ["pothos", "Epipremnum"], ["houseplant"]),
    "snake_plant": ("Snake plant", ["snake plant", "Sansevieria", "Dracaena trifasciata"], ["succulent", "houseplant"]),
    "peace_lily": ("Peace lily", ["peace lily"], ["houseplant"]),
    "spider_plant": ("Spider plant", ["spider plant"], ["houseplant"]),
    "aloe_vera": ("Aloe vera", ["aloe", "aloe vera"], ["succulent", "houseplant"]),
    "chinese_evergreen": ("Chinese evergreen", ["Chinese evergreen"], ["houseplant"]),
    "monstera": ("Monstera", ["monstera"], ["houseplant"]),
    "african_violet": ("African violet", ["African violet"], ["houseplant"]),
    "dracaena": ("Dracaena", ["dracaena", "Dracaena deremensis"], ["houseplant"]),
}
GROUPS = ["houseplant", "succulent"]

# -------------------------------------------------------------------- sources
NO_LICENSE = "No explicit reuse or license statement found on the page (university copyright notice only)."
SOURCES = {
    "src_clemson_jade": dict(
        title="Jade Plant", publisher="Clemson Cooperative Extension, Home & Garden Information Center",
        url="https://hgic.clemson.edu/factsheet/jade-plant/", date="Revised 2015-10-16",
        notes="Page says recommendations are for South Carolina conditions. Two reads of the page differed slightly (see unsure records)."),
    "src_clemson_pothos": dict(
        title="How to Grow Pothos Indoors (Epipremnum spp.): Care, Cultivars, and Common Problems",
        publisher="Clemson Cooperative Extension, Home & Garden Information Center",
        url="https://hgic.clemson.edu/factsheet/how-to-grow-pothos-indoors-epipremnum-spp-care-cultivars-and-common-problems/",
        date="Published 2026-01-30 (as shown on page)", notes="South Carolina conditions."),
    "src_psu_snake_plant": dict(
        title="Snake Plant: A Forgiving, Low-maintenance Houseplant", publisher="Penn State Extension",
        url="https://extension.psu.edu/snake-plant-a-forgiving-low-maintenance-houseplant", date="Updated 2023-09-20", notes=""),
    "src_psu_houseplant_problems": dict(
        title="Preventing, Diagnosing, and Correcting Common Houseplant Problems",
        publisher="Penn State Extension (College of Agricultural Sciences, Horticulture)",
        url="https://oc4h.ucanr.edu/sites/default/files/2020-07/330401.pdf", date="Copy read is dated 2006-08-09",
        notes=("Facts were read from this mirrored PDF copy. The current Penn State page is "
               "https://extension.psu.edu/preventing-diagnosing-and-correcting-common-houseplant-problems "
               "(search snippet showed 'Updated March 14, 2023'); that URL did not load the expected page when fetched, "
               "so the current version was NOT read directly. Cite the Penn State page, but re-check wording against it.")),
    "src_isu_diagnosing": dict(
        title="Diagnosing Houseplant Problems", publisher="Iowa State University Extension and Outreach",
        url="https://yardandgarden.extension.iastate.edu/how-to/diagnosing-houseplant-problems", date="Last reviewed 2024-01",
        notes="Main page is brief; it lists many pests/diseases by name with no detail."),
    "src_illinois_houseplants": dict(
        title="Houseplants (Knox County Master Gardeners)", publisher="University of Illinois Extension",
        url="https://extension.illinois.edu/sites/default/files/hkmw-_houseplants.pdf", date="2011-01",
        notes="Short general guide; gives light needs per plant but few plant-specific problems."),
}
for s in SOURCES.values():
    s["license"] = NO_LICENSE
    s["redistributable"] = "unknown"
    s["policy"] = "Store short paraphrased facts plus URL only. Do not store page text. Get permission before public release."
    s["date_accessed"] = "2026-10-02"

# -------------------------------------------------------------------- records
RECORDS = []
SYM_LABEL = {s[0]: s[1].lower() for s in SYMPTOMS}


def rec(kind="problem", plants=None, groups=None, parts=None, symptoms=None, cause=None, cat=None,
        summary="", src=None, qs=None, actions=None, inspect=None, caveats="", unsure=False,
        notes="", symptoms_stated=True, locs=None):
    r = {
        "record_id": "rec_%03d" % (len(RECORDS) + 1),
        "kind": kind,
        "plants": plants or [],
        "plant_groups": groups or [],
        "plant_parts": parts or ["leaf"],
        "symptoms": symptoms or [],
        "symptoms_stated": bool(symptoms) and symptoms_stated,
        "location_patterns": locs or [],
        "cause": cause,
        "cause_category": cat,
        "summary": summary,
        "distinguishing_questions": [{"question": q, "basis": b} for q, b in (qs or [])],
        "next_actions": actions or [],
        "inspect_next": [{"item": i, "basis": b} for i, b in (inspect or [])],
        "caveats": caveats,
        "unsure": unsure,
        "review_notes": notes,
        "source_id": src,
        "source_url": SOURCES[src]["url"],
        "status": "draft",
    }
    RECORDS.append(r)
    return r


def abiotic(symptoms, items, src="src_psu_houseplant_problems", parts=None):
    """One record per cause the page lists for a symptom."""
    for cause, cat, q in items:
        names = " / ".join(SYM_LABEL[s] for s in symptoms)
        rec(symptoms=symptoms, cause=cause, cat=cat, groups=["houseplant"], parts=parts,
            summary="The source lists %s as a possible cause of %s." % (cause, names),
            qs=[(q, "derived_from_cause")], src=src)


D = "derived_from_cause"
P = "page"
HP = ["houseplant"]
PSU = "src_psu_houseplant_problems"

# --- Generic pests (Penn State table)
rec(groups=HP, symptoms=["stunted_growth", "curling", "distorted_growth", "visible_insects"], cause="Aphids", cat="pest",
    summary="Tiny green, brown or black insects sit on the undersides of leaves; growth is stunted and leaves curl or distort.",
    qs=[("Are there tiny green, brown or black insects on the undersides of leaves?", P)],
    inspect=[("Look closely at the undersides of leaves", P)], src=PSU,
    notes="Page gives no management for this pest.")
rec(groups=HP, parts=["leaf", "stem"], symptoms=["visible_insects", "stunted_growth"], cause="Mealybugs", cat="pest",
    summary="White, cottony-looking scale insects on stems and the undersides of leaves; plant growth is stunted.",
    qs=[("Do you see white cottony bits on the stems or under the leaves?", P)],
    inspect=[("Check stems and the undersides of leaves", P)], src=PSU, notes="Page gives no management for this pest.")
rec(groups=HP, symptoms=["webbing", "yellowing", "distorted_growth"], cause="Mites", cat="pest",
    summary="Tiny light-colored arachnids; fine webbing appears on foliage and leaves become distorted and yellowish.",
    qs=[("Is there fine webbing on the leaves?", P)], src=PSU, notes="Page gives no management for this pest.")
rec(groups=HP, parts=["leaf", "stem"], symptoms=["visible_insects", "stunted_growth"], cause="Scale insects", cat="pest",
    summary="Oval or round brown insects on stems and leaves; they suck plant juices, which leads to poor, stunted growth.",
    qs=[("Are there small oval or round brown bumps on the stems or leaves?", P)], src=PSU,
    notes="Page gives no management for this pest.")
rec(groups=HP, parts=["leaf", "flower"], symptoms=["distorted_growth", "faded_color"], cause="Thrips", cat="pest",
    summary="Extremely tiny insects (adults light tan to dark brown); leaves and flowers become distorted and discolored.",
    src=PSU, notes="Page gives no management for this pest. Insects are too small to see easily in a photo.")
rec(groups=HP, symptoms=["yellowing", "faded_color", "visible_insects"], cause="Whiteflies", cat="pest",
    summary="Small white, gnat-like insects; leaves turn pale yellow or white.",
    qs=[("Do small white flying insects rise when you touch the plant?", D)], src=PSU,
    notes="Page gives no management. The question is derived from the 'gnat-like' description.")

# --- Generic diseases (Penn State table)
rec(groups=HP, symptoms=["yellowing", "brown_tips_edges"], cause="Anthracnose (fungal)", cat="disease",
    summary="Leaf tips turn yellow and then brown, and the whole leaf may die.",
    actions=["Remove infected leaves", "Avoid misting"], src=PSU)
rec(groups=HP, symptoms=["brown_spots"], cause="Leaf spot diseases (fungal or bacterial)", cat="disease",
    summary="Fungal spots are brown with a yellow halo; bacterial spots look water-soaked with a yellow halo. Fungal structures may be visible under magnification.",
    qs=[("Are the spots brown with a yellow ring, or do they look water-soaked?", P)],
    actions=["Remove infected leaves", "Increase air circulation", "Avoid wetting the leaves"],
    inspect=[("Look at the spots with a magnifier for tiny fungal structures", P)], src=PSU)
rec(groups=HP, symptoms=["white_powdery_coating", "distorted_growth", "leaf_drop"], cause="Powdery mildew (fungal)", cat="disease",
    summary="White powdery growth on foliage, with distorted leaves and possible leaf drop.",
    actions=["Increase air circulation", "Avoid saturated soil", "Remove severely infected foliage"], src=PSU)
rec(groups=HP, parts=["roots", "stem"], symptoms=["soft_mushy_stem", "wilting_drooping"], cause="Root and stem rots", cat="disease",
    summary="Roots turn soft and brown or black; stems go soft with a brown or black ring near the soil line; the plant wilts and can die.",
    qs=[("Is the stem soft or dark near the soil line, or are the roots soft and brown/black?", P)],
    actions=["Avoid overwatering", "Remove infected plants",
             "If only partly infected, cut off infected roots and repot in sterile mix and a clean pot"],
    inspect=[("Check the roots and the stem near the soil line", P)], src=PSU)

# --- Generic abiotic (Penn State symptom -> cause table)
abiotic(["yellowing"], [
    ("overwatering or poor soil drainage", "watering", "Does the soil stay wet for days after watering?"),
    ("insufficient light", "environment", "Is the plant in a dim spot?"),
    ("low humidity", "environment", "Is the air very dry (for example from heating)?"),
    ("cold draft injury", "environment", "Is the plant near a cold window or draft?"),
])
abiotic(["scorched_leaves"], [("direct sun exposure", "environment", "Does direct sun hit the leaves?")])
abiotic(["brown_tips_edges"], [
    ("fertilizer or pesticide burn", "nutrient", "Have you fertilized or sprayed the plant recently?"),
    ("soft water", "environment", "Do you water with softened water?"),
    ("soil staying dry for long periods", "watering", "Does the soil dry out completely for long stretches?"),
    ("low temperature", "environment", "Has the plant been exposed to cold?"),
])
abiotic(["small_leaves", "wilting_drooping"], [
    ("soil alternating between too wet and too dry", "watering", "Does the soil swing between soggy and very dry?")])
abiotic(["stunted_growth"], [
    ("incorrect lighting (source says 'weak growth')", "environment", "Is the plant getting the light level it needs?"),
    ("root damage from excessive moisture (source says 'weak growth')", "watering", "Does the soil stay wet, or do the roots look damaged?"),
])
abiotic(["leggy_stretched"], [("insufficient or poor light (source says 'spindly')", "environment", "Is the plant stretching toward a light source?")])
abiotic(["leaf_drop"], [
    ("overwatering (source says 'general defoliation')", "watering", "Does the soil stay wet for days after watering?"),
    ("poor lighting (source says 'general defoliation')", "environment", "Is the plant getting enough light?"),
    ("cold injury (source says 'general defoliation')", "environment", "Has the plant been exposed to cold?"),
])

# --- Generic, Iowa State
ISU = "src_isu_diagnosing"
for cause, cat in [("low humidity", "environment"), ("over-fertilizing", "nutrient")]:
    rec(groups=HP, symptoms=["brown_tips_edges"], cause=cause, cat=cat,
        summary="The source gives %s as an example cause of brown leaf tips and notes several factors often combine, so all contributing factors should be addressed." % cause,
        qs=[("Is the air dry?" if cause == "low humidity" else "Have you fertilized heavily or recently?", D)], src=ISU,
        caveats="Source says multiple factors often combine.")
rec(groups=HP, parts=["soil", "leaf"], symptoms=["visible_insects"], cause="Fungus gnats from wet soil", cat="watering",
    summary="The source links fungus gnats to wet soil and says treating the insects with insecticide won't help unless the wet soil is fixed.",
    qs=[("Is the soil staying wet?", D)], actions=["Address the wet soil that is attracting the gnats"], src=ISU,
    notes="Page gives no symptoms for gnats beyond the name.", symptoms_stated=False)

# --- Generic, Illinois
IL = "src_illinois_houseplants"
rec(groups=HP, parts=["whole_plant"], symptoms=[], cause="Over-fertilizing", cat="nutrient",
    summary="The source says extra fertilizer when the plant is not actively growing can cause severe damage or plant death.",
    actions=["Fertilize only during active growth (March to September in the source)",
             "Use a water-soluble fertilizer as the package directs", "Avoid fertilizing in winter"],
    qs=[("Have you fertilized in winter or more than the label says?", D)], src=IL, symptoms_stated=False,
    notes="Source is a Midwest US guide; seasons may not fit other regions.")
rec(groups=HP, parts=["whole_plant"], symptoms=["scorched_leaves"], cause="Cold or heat from window placement", cat="environment",
    summary="The source says windows can expose plants to cold in winter and scorching heat in summer.",
    actions=["Keep plants from touching the window glass", "Rotate plants about quarterly for even growth"],
    qs=[("Does the plant sit right against a window?", D)], src=IL)
rec(groups=HP, parts=["roots"], symptoms=[], cause="Root rot from standing water", cat="watering",
    summary="The source says letting plants sit in standing water leads to root rot.",
    actions=["Make sure the pot drains", "Use a pebble tray so the pot does not sit in water"], src=IL, symptoms_stated=False,
    qs=[("Is the pot sitting in water?", D)])
rec(groups=HP, parts=["roots"], symptoms=[], cause="Root burn from salt buildup", cat="nutrient",
    summary="The source says excess salts building up in the soil can burn roots.",
    actions=["When watering, let water run out through the bottom of the pot"], src=IL, symptoms_stated=False)
rec(groups=HP, parts=["whole_plant"], symptoms=[], cause="Low winter humidity from furnace heating", cat="environment",
    summary="The source says furnace operation lowers indoor humidity in winter.",
    actions=["Use a humidifier", "Group plants together", "Use shallow water trays or pebble trays nearby", "Mist plants"],
    src=IL, symptoms_stated=False, notes="Page names no symptoms for low humidity.")

# --- Jade (Clemson)
CJ = "src_clemson_jade"
JG = ["succulent", "houseplant"]
rec(plants=["jade"], groups=JG, parts=["roots"], symptoms=[], cause="Root rot from poor drainage or too-frequent watering", cat="watering",
    summary="Root rot comes from soil that does not drain quickly or from watering too often.",
    actions=["Use a well-drained soil mix (cactus mix with organic matter, or sterilized organic soil with peat moss and coarse sand)"],
    qs=[("Does water drain slowly, or do you water very often?", D)], src=CJ, symptoms_stated=False,
    notes="Page names no visible symptoms for root rot.")
rec(plants=["jade"], groups=JG, symptoms=["leaf_drop"], cause="Plant allowed to become extremely dry", cat="watering",
    summary="Jade plants drop leaves when allowed to get extremely dry.", actions=["Keep watering appropriately consistent"],
    qs=[("Has the soil been completely dry for a long time?", D)], src=CJ)
rec(plants=["jade"], groups=JG, parts=["leaf", "stem"], symptoms=["visible_insects"], cause="Mealybugs", cat="pest",
    summary="Mealybugs look like white puffs of cotton and are the most common insect pest on jade.",
    actions=["Wipe them off with alcohol on a cotton swab"],
    qs=[("Do you see white cotton-like puffs on the plant?", P)],
    inspect=[("Check stems and leaf joints for white puffs", D)],
    caveats="Source cautions that insecticidal soap may damage jade plants.", src=CJ)
rec(plants=["jade"], groups=JG, symptoms=["faded_color", "stippling"], cause="Spider mites", cat="pest",
    summary="Jade plants with spider mites lose green color and look dusty or speckled.",
    qs=[("Do the leaves look dusty or speckled, and have they lost color?", P)], src=CJ,
    notes="Page gives no management for spider mites.")
rec(plants=["jade"], groups=JG, symptoms=["brown_spots", "leaf_drop", "stunted_growth"], cause="Too little light or water, or wrong temperature/drafts", cat="environment",
    summary="One read of the page said insufficient light or water causes dwarfing, spotting and leaf drop, and that wrong temperatures or drafts cause problems.",
    src=CJ, unsure=True, notes="This appeared in only one of two reads of the page. Check the page before approving.")
rec(kind="plant_profile", plants=["jade"], groups=JG, parts=["leaf", "stem"], symptoms=[],
    summary="Normal appearance: fleshy, glossy round or oval leaves in dark green, blue-gray or edged in red, on stout brown stems.", src=CJ)

# --- Pothos (Clemson)
CP = "src_clemson_pothos"
rec(plants=["pothos"], groups=HP, parts=["roots"], symptoms=[], cause="Root rot from overwatering or poorly draining soil", cat="watering",
    summary="Root rot is a common houseplant problem caused by overwatering or poorly draining soil.",
    actions=["Use a well-draining soil mix", "Water properly"], qs=[("Does the soil stay wet for days?", D)], src=CP,
    symptoms_stated=False, notes="Page names no visible symptoms.")
rec(plants=["pothos"], groups=HP, symptoms=["yellowing"], cause="Overwatering", cat="watering",
    summary="The source says yellow pothos leaves are often caused by overwatering.",
    qs=[("Does the soil stay wet for days after watering?", D)], src=CP)
rec(plants=["pothos"], groups=HP, symptoms=["yellowing"], cause="Low fertility", cat="nutrient",
    summary="The source says yellow pothos leaves can come from low fertility.",
    actions=["Use a houseplant fertilizer about every other month in spring and summer"],
    qs=[("Has the plant been fertilized recently?", D)], src=CP)
for cause in ["low humidity", "intense light"]:
    rec(plants=["pothos"], groups=HP, symptoms=["scorched_leaves", "brown_tips_edges"], cause=cause, cat="environment",
        summary="The source says scorched leaves and dying tips on pothos are often caused by %s." % cause,
        actions=["Give bright, indirect light", "Keep humidity higher"],
        qs=[("Is the air dry?" if cause == "low humidity" else "Does strong direct light reach the leaves?", D)], src=CP)
rec(plants=["pothos"], groups=HP, symptoms=[], cause="Spider mites or mealybugs", cat="pest",
    summary="The source names spider mites and mealybugs as possible pests but says pothos is generally pest-free indoors.",
    src=CP, unsure=True, symptoms_stated=False, notes="Thin: no symptoms or management given on the page (it refers to another publication).")
rec(kind="plant_profile", plants=["pothos"], groups=HP, parts=["leaf"], symptoms=[],
    summary="Normal appearance: slightly heart-shaped, shiny leaves a few inches long that stay whole; vines give a bushy look.", src=CP)

# --- Snake plant (Penn State)
SN = "src_psu_snake_plant"
rec(plants=["snake_plant"], groups=JG, parts=["roots"], symptoms=[], cause="Root rot from overwatering", cat="watering",
    summary="The source calls root rot a common problem for snake plants, caused by overwatering.",
    actions=["Water only when the soil is dry", "Use a well-drained cactus mix or soil with perlite", "Use a pot with drainage holes"],
    qs=[("Do you water before the soil has dried out?", D)], src=SN, symptoms_stated=False,
    notes="Page names no visible symptoms.")
rec(plants=["snake_plant"], groups=JG, symptoms=[], cause="Mealybugs or spider mites", cat="pest",
    summary="The source mentions mealybugs and spider mites as pests but gives no symptoms or control steps.",
    src=SN, unsure=True, symptoms_stated=False, notes="Thin mention only.")
rec(kind="plant_profile", plants=["snake_plant"], groups=JG, parts=["whole_plant"], symptoms=[],
    summary="The source describes it as a long-lived, unfussy succulent houseplant that tolerates low light.", src=SN)

# --- Plant light profiles (Illinois)
for pid, light, extra in [
    ("pothos", "low light", ""), ("chinese_evergreen", "low light", ""), ("snake_plant", "low light", ""),
    ("spider_plant", "medium light", ""), ("peace_lily", "medium light", " It prefers consistently moist soil and does not like to dry out."),
    ("african_violet", "medium light", ""), ("aloe_vera", "high light", ""),
]:
    rec(kind="plant_profile", plants=[pid], groups=HP, parts=["whole_plant"], symptoms=[],
        summary="The source lists this plant under %s.%s" % (light, extra), src=IL,
        notes="Light need only; the page gives no problems for this plant.")

# ------------------------------------------------------------------- schema
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "PlantLens KB record",
    "type": "object",
    "required": ["record_id", "kind", "plants", "plant_groups", "plant_parts", "symptoms", "symptoms_stated",
                 "cause", "cause_category", "summary", "distinguishing_questions", "next_actions",
                 "inspect_next", "unsure", "source_id", "source_url", "status"],
    "properties": {
        "record_id": {"type": "string", "pattern": "^rec_[0-9]{3,}$"},
        "kind": {"enum": ["problem", "plant_profile"]},
        "plants": {"type": "array", "items": {"type": "string"}},
        "plant_groups": {"type": "array", "items": {"type": "string"}},
        "plant_parts": {"type": "array", "items": {"type": "string"}},
        "symptoms": {"type": "array", "items": {"type": "string"}},
        "symptoms_stated": {"type": "boolean", "description": "False when the source page gives no symptoms for this problem."},
        "location_patterns": {"type": "array", "items": {"type": "string"}},
        "cause": {"type": ["string", "null"]},
        "cause_category": {"enum": CAUSE_CATEGORIES + [None]},
        "summary": {"type": "string", "minLength": 10, "description": "Own words, 1-3 sentences, only what the source states."},
        "distinguishing_questions": {"type": "array", "items": {
            "type": "object", "required": ["question", "basis"],
            "properties": {"question": {"type": "string"}, "basis": {"enum": ["page", "derived_from_cause"]}}}},
        "next_actions": {"type": "array", "items": {"type": "string"}},
        "inspect_next": {"type": "array", "items": {
            "type": "object", "required": ["item", "basis"],
            "properties": {"item": {"type": "string"}, "basis": {"enum": ["page", "derived_from_cause"]}}}},
        "caveats": {"type": "string"},
        "unsure": {"type": "boolean"},
        "review_notes": {"type": "string"},
        "source_id": {"type": "string"},
        "source_url": {"type": "string", "pattern": "^https?://"},
        "status": {"enum": ["draft", "reviewed"]},
    },
    "additionalProperties": False,
}

# -------------------------------------------------------------------- write
dump_yaml("vocab/symptoms.yaml", [{"id": i, "label": l, "synonyms": [x.strip() for x in s.split(";")]} for i, l, s in SYMPTOMS])
dump_yaml("vocab/plant_parts.yaml", PLANT_PARTS)
dump_yaml("vocab/cause_categories.yaml", CAUSE_CATEGORIES)
dump_yaml("vocab/location_patterns.yaml", LOCATION_PATTERNS)
dump_yaml("vocab/plants.yaml", {
    "groups": GROUPS,
    "plants": [{"id": k, "name": v[0], "aliases": v[1], "groups": v[2]} for k, v in PLANTS.items()]})
dump_yaml("sources/sources.yaml", [dict(source_id=k, **v) for k, v in SOURCES.items()])
out("schema/record.schema.json", json.dumps(SCHEMA, indent=2))
out("records/draft/records_batch1.json", json.dumps(RECORDS, indent=2, ensure_ascii=False))

os.makedirs(os.path.join(KB, "review"), exist_ok=True)
with open(os.path.join(KB, "review", "review_batch1.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["record_id", "kind", "plants", "symptoms", "cause", "summary", "source_url",
                "unsure", "derived_items", "decision (approve/edit/reject)", "your_notes"])
    for r in RECORDS:
        derived = sum(q["basis"] != "page" for q in r["distinguishing_questions"]) + \
                  sum(i["basis"] != "page" for i in r["inspect_next"])
        w.writerow([r["record_id"], r["kind"], ";".join(r["plants"]) or "(any houseplant)", ";".join(r["symptoms"]),
                    r["cause"] or "", r["summary"], r["source_url"], "YES" if r["unsure"] else "", derived, "", ""])

print("records:", len(RECORDS))
