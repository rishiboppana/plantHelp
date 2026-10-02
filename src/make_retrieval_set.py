"""Generates kb/eval/retrieval_set.jsonl. Expected ids are written by hand from what each record's source says; review before trusting."""
import json
from pathlib import Path

ID = dict(overwater=1, underwater=2, rootrot=3, salts=4, nitrogen=5, micro=6, lowlight=7, sunburn=8, cold=9, humidity=10, moved=11,
          potbound=12, spider=13, mealy=14, aphid=15, scale=16, whitefly=17, thrips=18, gnats=19, broadmite=20, powdery=21,
          graymold=22, fungalspot=23, bactspot=24, stemrot=25, canker=26, virus=27, chewing=28, chemical=29)
Q = []


def q(kind, text, symptoms, expected, parts=(), plant=None, none=False, notes=""):
    Q.append({"id": f"q{len(Q)+1:03d}", "kind": kind, "query_text": text,
              "query_observation": {"plant": {"id": plant, "confidence": "high" if plant else "unknown"}, "plant_parts": list(parts),
                                    "symptoms": symptoms, "location_patterns": [], "description": text},
              "expected_record_ids": [f"rec_{ID[e]:06d}" for e in expected], "expected_coverage": "none" if none else "in_scope", "notes": notes})


# --- lay phrasing, structured symptoms present
q("lay", "the leaves have tiny pale dots and I can see thin silky threads near the new growth", ["stippling", "webbing"], ["spider"], ["leaf"])
q("lay", "white cottony fluff tucked where the leaf meets the stem", ["white_fluff"], ["mealy"], ["leaf", "stem"], "pothos")
q("lay", "leaves feel sticky and there are little green bugs on the new shoots", ["sticky_residue", "visible_insects"], ["aphid"], ["leaf"])
q("lay", "hard brown bumps along the stem that come off with a fingernail", ["bumps_scale"], ["scale"], ["stem"])
q("lay", "tiny white flies erupt when I shake the plant", ["visible_insects"], ["whitefly"], ["leaf"])
q("lay", "little black flies hovering over the soil, which stays damp", ["visible_insects", "soil_wet"], ["gnats"], ["soil"])
q("lay", "white dusty film on the leaves, like flour", ["powdery_coating"], ["powdery"], ["leaf"])
q("lay", "grey fuzz on old dead flowers and bottom leaves", ["fuzzy_mold"], ["graymold"], ["leaf", "flower"])
q("lay", "round tan spots with dark edges scattered over the leaves", ["brown_spots"], ["fungalspot", "sunburn", "cold"], ["leaf"], notes="ambiguous: spots have several causes")
q("lay", "greasy looking dark green spots, easiest to see from underneath", ["water_soaked_spots"], ["bactspot"], ["leaf"])
q("lay", "stem base is mushy and smells bad and the plant is collapsing", ["soft_stem_base", "wilting"], ["stemrot", "overwater"], ["stem"])
q("lay", "pulled it out of the pot and the roots are black and squishy", ["dark_soft_roots", "wilting"], ["rootrot"], ["root"])
q("lay", "leaf tips turned crispy brown and there is white crust on the soil", ["browning", "soil_crust"], ["salts"], ["leaf"])
q("lay", "plant is long and stretchy, reaching toward the window, no flowers", ["spindly_growth", "few_flowers"], ["lowlight"], ["whole_plant"])
q("lay", "leaves look washed out and white on the side facing the glass", ["bleaching"], ["sunburn"], ["leaf"])
q("lay", "leaves went black after a cold night near the window", ["blackening"], ["cold"], ["leaf"])
q("lay", "leaves are patchy green and yellow and the plant stays small", ["mottling", "distorted_growth"], ["virus"], ["leaf"])
q("lay", "ragged holes in the leaves after summer outside", ["holes_chewing"], ["chewing"], ["leaf"])
q("lay", "new leaves are thick, brittle and curled downward at the edges", ["distorted_growth", "leaf_curl"], ["broadmite", "aphid"], ["leaf"], notes="ambiguous: both listed as causing curl/distortion on new growth")
q("lay", "drooping plant, soil is bone dry and pulling from the pot", ["wilting", "soil_dry"], ["underwater"], ["whole_plant"])
q("lay", "plant is drooping and the soil never seems to dry out", ["wilting", "soil_wet"], ["overwater", "rootrot", "gnats"], ["whole_plant"], notes="ambiguous")
q("lay", "bottom leaves are going pale yellow, the rest looks ok", ["yellowing"], ["nitrogen"], ["leaf"])
q("lay", "newest leaves are yellow-green while older ones are fine", ["yellowing"], ["micro", "overwater"], ["leaf"])
q("lay", "dropping leaves right after I brought it home", ["leaf_drop", "yellowing"], ["moved"], ["whole_plant"])
q("lay", "silvery patches and tiny black specks on leaves", ["stippling"], ["thrips"], ["leaf"])
q("lay", "sticky shiny leaves with a black sooty film", ["sticky_residue", "sooty_mold"], ["aphid", "scale", "mealy"], ["leaf"], notes="ambiguous: honeydew producers")
q("lay", "roots are circling the pot and growth has stalled", ["yellowing"], ["potbound"], ["root"])
q("lay", "tips are brown, plant sits next to a heating vent", ["browning"], ["humidity", "salts"], ["leaf"], notes="ambiguous")
q("lay", "weird blotches after I sprayed the plant last week", ["brown_spots"], ["chemical"], ["leaf"])
# --- technical phrasing
q("technical", "chlorosis of older foliage consistent with nitrogen deficiency", ["yellowing"], ["nitrogen"], ["leaf"])
q("technical", "Tetranychus infestation with stipple injury", ["stippling"], ["spider"], ["leaf"])
q("technical", "Botrytis blight on senescent flowers", ["fuzzy_mold"], ["graymold"], ["flower"])
q("technical", "Erysiphe fungal growth on leaf surface", ["powdery_coating"], ["powdery"], ["leaf"])
q("technical", "Phytophthora and Pythium root decay", ["dark_soft_roots"], ["rootrot"], ["root"])
q("technical", "Pseudomonas leaf spot with chlorotic halo", ["water_soaked_spots"], ["bactspot"], ["leaf"])
q("technical", "honeydew excretion by soft scale", ["sticky_residue"], ["scale", "aphid", "mealy", "whitefly"], ["leaf"], notes="ambiguous")
q("technical", "cyclamen mite injury on flowering plant", ["few_flowers"], ["broadmite"], ["flower"])
q("technical", "vascular bacterial infection causing cankers", ["soft_stem_base"], ["stemrot", "canker"], ["stem"])
# --- unknown plant / description only (symptom list empty: vocabulary-mismatch probes)
q("vocab", "there are tiny dots all over the leaves and fine webs", [], ["spider"], notes="no structured symptoms; text only")
q("vocab", "white fuzzy stuff on the leaf joints", [], ["mealy"])
q("vocab", "the plant looks sunburnt after I moved it outside", [], ["sunburn"])
q("vocab", "leaves are chewed up and slimy trails", [], ["chewing"])
q("vocab", "gnats flying around the pot", [], ["gnats"])
q("vocab", "mushy rotten stem", [], ["stemrot", "overwater"])
q("vocab", "dusty powder on leaves", [], ["powdery"])
q("vocab", "the plant froze near the window and now leaves are dead", [], ["cold"])
# --- known plant, part mismatch / filter stress
q("filter", "yellow leaves and sticky residue on my pothos", ["yellowing", "sticky_residue"], ["scale", "whitefly", "mealy"], ["leaf"], "pothos")
q("filter", "my orchid flower has grey mold on old blooms", ["fuzzy_mold"], ["graymold"], ["flower"], "orchid")
q("filter", "my fern fronds have brown bumps", ["bumps_scale"], ["scale"], ["leaf"], "boston_fern", notes="source notes scale on ferns can look like spores")
q("filter", "jade plant drooping with soft base", ["wilting", "soft_stem_base"], ["overwater", "stemrot"], ["stem"], "jade")
q("filter", "african violet leaf spots", ["brown_spots"], ["fungalspot", "sunburn", "cold", "bactspot"], ["leaf"], "african_violet", notes="ambiguous")
q("filter", "peace lily with brown tips", ["browning"], ["salts", "underwater", "humidity"], ["leaf"], "peace_lily", notes="ambiguous")
# --- out of scope / not covered: expect coverage none
q("oos", "my dog chewed the pot and the saucer cracked", [], [], none=True)
q("oos", "qzxv wplk jrmt", [], [], none=True)
q("oos", "what is the capital of France", [], [], none=True)
q("oos", "how do I sharpen garden shears", [], [], none=True)

p = Path(__file__).resolve().parents[1] / "kb" / "eval" / "retrieval_set.jsonl"
p.write_text("\n".join(json.dumps(x) for x in Q) + "\n")
print(len(Q), "queries ->", p)
