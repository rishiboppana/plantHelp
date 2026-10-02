# Symptom vocabulary (provisional)

Use these ids in the observation object and these terms when describing what you see. The knowledge base uses the same words, which is what makes retrieval work.

> This list is a starting point. Once the knowledge base exists, replace it with the contents of `kb/vocab/symptoms.yaml` so the model and the index share a single source of truth.

## Plant parts
`leaf`, `stem`, `fruit`, `flower`, `whole_plant`, `roots`, `soil`

## Symptoms

| id | What it looks like | Lay wording users may use |
|---|---|---|
| `yellowing` | Leaf turns yellow, whole leaf or between veins | "yellow leaves", "pale leaves" |
| `brown_spots` | Brown spots or patches on leaves | "brown dots", "spotty leaves" |
| `black_spots` | Dark or black spots, sometimes with a yellow ring | "black patches" |
| `brown_tips_edges` | Brown, dry tips or leaf edges | "crispy tips", "burnt edges" |
| `curling` | Leaves curl, cup, or twist | "curled leaves" |
| `wilting_drooping` | Leaves or stems limp and drooping | "droopy", "wilted" |
| `holes_chewed` | Holes or chewed edges | "leaves eaten", "bitten" |
| `stippling` | Tiny pale dots across the leaf surface | "speckled leaves" |
| `white_powdery_coating` | White powder-like film on leaves or stems | "white dust" |
| `fuzzy_mold_growth` | Fuzzy or mold-like growth on leaves, stems, or soil | "mold", "fuzz" |
| `sticky_residue` | Sticky, shiny film on leaves | "sticky leaves" |
| `webbing` | Fine webbing on leaves or between stems | "cobwebs" |
| `visible_insects` | Insects or insect-like bumps visible | "bugs", "white fluff" |
| `leaf_drop` | Leaves falling off | "dropping leaves" |
| `stunted_growth` | Little or no new growth, small new leaves | "not growing" |
| `leggy_stretched` | Long, stretched stems with wide gaps between leaves | "leggy", "reaching" |
| `soft_mushy_stem` | Soft, dark, or mushy stem or base | "rotting" |
| `faded_color` | Overall washed-out color, loss of normal pattern | "losing color" |

## Location patterns
`lower_leaves_first`, `new_growth_first`, `leaf_edges`, `between_veins`, `one_side_only`, `whole_plant`, `scattered`

## Extent
`few_leaves`, `many_leaves`, `whole_plant`

## Other visible clues (use as `other_visible`)
`soil_looks_wet`, `soil_looks_dry`, `soil_crusted`, `pot_no_drainage`, `webbing`, `insects_visible`, `dust_on_leaves`, `direct_sun_exposure`

## Rules for describing
- Use the closest id. If nothing fits, describe it in plain words in `other_visible` instead of inventing an id.
- Use mold-like growth or white powdery coating, not a disease name. A photo shows the appearance, not the pathogen.
- Report only what is visible. Do not infer watering or light from the photo unless the soil, pot, or light is actually shown.
