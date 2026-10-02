# Symptom vocabulary

GENERATED from `kb/vocab/symptoms.yaml` by `python -m src.gen_skill_vocab`. Do not edit by hand; edit the yaml and regenerate. The knowledge base uses the same ids, which is what makes retrieval work.

## Plant parts
`leaf`, `stem`, `flower`, `fruit`, `root`, `soil`, `whole_plant`

## Symptoms

| id | What it looks like | Lay wording users may use |
|---|---|---|
| `yellowing` | Yellowing leaves | "yellow leaves", "pale leaves", "chlorosis" |
| `browning` | Browning leaves | "brown leaves", "brown tips", "brown edges" |
| `brown_spots` | Brown or dark spots | "leaf spots", "dark spots", "blotches" |
| `blackening` | Blackened tissue | "black leaves", "black stems", "blackening" |
| `bleaching` | Bleached or whitened leaves | "white patches", "washed out", "faded" |
| `stippling` | Fine stippling | "tiny dots", "speckled leaves", "pin-prick dots" |
| `mottling` | Mottled pattern | "mosaic", "patchy color", "uneven color" |
| `wilting` | Wilting or drooping | "drooping", "limp leaves", "sagging" |
| `leaf_curl` | Curling leaves | "curled leaves", "rolled leaves", "cupping" |
| `distorted_growth` | Distorted or stunted growth | "stunted", "deformed", "twisted new growth" |
| `leaf_drop` | Leaf drop | "falling leaves", "dropping leaves", "shedding" |
| `spindly_growth` | Spindly or leggy growth | "leggy", "stretched", "etiolated" |
| `holes_chewing` | Holes or chewed leaves | "chewed edges", "holes in leaves", "eaten leaves" |
| `powdery_coating` | White powdery coating | "white powder", "powdery mildew look", "dusty white film" |
| `fuzzy_mold` | Fuzzy mold growth | "gray fuzz", "mold", "fuzzy growth" |
| `white_fluff` | White cottony or waxy fluff | "cottony masses", "white wax", "white fuzz on stems" |
| `sticky_residue` | Sticky residue | "honeydew", "sticky leaves", "shiny sticky film" |
| `visible_insects` | Visible insects | "bugs", "aphids", "flying insects" |
| `webbing` | Fine webbing | "cobwebs", "silk threads", "web on leaves" |
| `bumps_scale` | Bumps on stems or leaves | "scale", "brown bumps", "shells on stem" |
| `soft_stem_base` | Soft or mushy stem base | "mushy stem", "rotting base", "stem rot" |
| `soil_wet` | Soil staying wet | "soggy soil", "waterlogged", "never dries" |
| `soil_dry` | Soil very dry | "bone dry", "pulling from pot edge", "hard soil" |
| `soil_crust` | Crust or deposits on soil | "white crust", "salt buildup", "mineral crust" |
| `few_flowers` | Few or no flowers | "not blooming", "no blooms", "flower drop" |
| `water_soaked_spots` | Water-soaked or oily spots | "greasy spots", "oily spots", "translucent spots" |
| `dark_soft_roots` | Dark or soft roots | "brown roots", "black roots", "rotted roots" |
| `sooty_mold` | Black sooty coating | "black film", "sooty mold", "black residue on leaves" |
| `dry_brown_patch` | Large dry brown patch | "big brown patch", "crispy patch", "papery brown area" |

## Location patterns
`lower_leaves_first`, `new_growth`, `leaf_edges`, `between_veins`, `one_side`, `whole_plant`, `undersides`

## Extent
`few_leaves`, `many_leaves`, `whole_plant`

## Other visible clues (use as `other_visible`)
`soil_looks_wet`, `soil_looks_dry`, `soil_crusted`, `pot_no_drainage`, `webbing`, `insects_visible`, `dust_on_leaves`, `direct_sun_exposure`

## Rules for describing
- Use the closest id. If nothing fits, describe it in plain words in `other_visible` instead of inventing an id.
- Use mold-like growth or white powdery coating, not a disease name. A photo shows the appearance, not the pathogen.
- Report only what is visible. Do not infer watering or light from the photo unless the soil, pot, or light is actually shown.
