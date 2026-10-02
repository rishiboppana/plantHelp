"""Batch 1 draft records, hand-extracted from the approved houseplant sources (2026-10-02).
Every fact below is stated in the cited source; nothing is added from memory. Writes kb/records/draft/houseplants_batch1.jsonl.
Run: python -m src.ingest.houseplants_batch1
"""
import json
from pathlib import Path

UC = ("src_ucipm_houseplant_problems", "https://ipm.ucanr.edu/home-and-landscape/houseplant-problems/")
UMD = ("src_umd_indoor_plant_problems", "https://extension.umd.edu/resource/diagnose-indoor-plant-problems")
ILL = ("src_illinois_troubleshooting", "https://extension.illinois.edu/sites/default/files/troubleshooting_houseplants_0.pdf")

R = []


def rec(src, cause, cat, symptoms, summary, qs, actions=(), inspect=(), parts=("leaf",), loc=(), caveats=None):
    R.append(dict(
        record_id=f"rec_{len(R)+1:06d}", plants=[], plant_groups=[], plant_parts=list(parts),
        symptoms=symptoms, location_patterns=list(loc), cause=cause, cause_category=cat, summary=summary,
        distinguishing_questions=[dict(question=q, if_yes="supports this cause", if_no="weakens this cause") for q in qs],
        next_actions=list(actions), inspect_next=list(inspect), caveats=caveats,
        source_id=src[0], source_url=src[1], status="draft"))


rec(UC, "overwatering or poor drainage", "watering", ["yellowing", "wilting", "soft_stem_base", "soil_wet"],
    "Overwatering and poor drainage can cause yellowing and dropping leaves, wilting, soft stem bases and soggy soil, and can lead to root decay.",
    ["Does the soil stay wet for days after watering?", "Does water drain out of the bottom of the pot?"],
    ["Let the soil dry as much as possible between waterings", "Make sure water can drain from the container"],
    ["Pull the plant out and check whether the roots are white and firm or dark and soft"], parts=("whole_plant", "soil"), loc=["whole_plant"],
    caveats="Wilting can also come from underwatering or too much light, so check the roots and soil.")
rec(UC, "underwatering or very dry soil", "watering", ["wilting", "browning", "soil_dry"],
    "Wilting is usually caused by underwatering or excessive light. Brown leaf tips or margins can result from excessively dry soil.",
    ["Is the soil dry well below the surface?", "Does the plant perk up after watering?"],
    ["Re-check the plant after watering", ],
    ["Check whether the soil pulls away from the pot or is dry deep down"], parts=("whole_plant", "soil"),
    caveats="Root decay from overwatering also causes wilting, so inspect the roots before assuming the plant is too dry.")
rec(UC, "root rot", "disease", ["wilting", "yellowing", "dark_soft_roots", "soil_wet"],
    "Root rot is often seen as wilting or discoloration above ground. Off-color roots (brownish to blackish), especially at the tips, indicate root rot; healthy roots are white. It is often associated with poor drainage and overwatering.",
    ["Are the roots dark and soft when you slide the plant out of its pot?", "Has the soil been staying wet or draining poorly?"],
    ["Improve drainage and watering frequency", "Remove rotted portions and repot the healthy sections in fresh, well-drained mix (UMD)"],
    ["Slide the plant out of the pot and look at the roots"], parts=("root", "whole_plant"), loc=["whole_plant"],
    caveats="Severely damaged plants may be best discarded (UMD).")
rec(UC, "fertilizer or salt buildup", "nutrient", ["browning", "soil_crust"],
    "Brown leaf tips or margins are usually caused by overfertilization, salt buildup, or excessively dry or wet soil. Fertilizer salts can also build up on containers.",
    ["Has the plant been fertilized often, or is there a white crust on the soil or pot?", "Does tap water leave deposits on the pot?"],
    ["Flush the soil with clear water to leach excess salts", "Scrub the edges of the pot (Illinois)"],
    ["Look for crust on the soil surface and pot rim"], loc=["leaf_edges"],
    caveats="Other causes of brown tips include too much sun or heat, low humidity and drafts.")
rec(UC, "nutrient deficiency (nitrogen)", "nutrient", ["yellowing"],
    "Yellow-green older leaves can be due to insufficient fertilizer, especially nitrogen. Weak growth or light green to yellow leaves may also come from root rot, too little or too much light, or sap-sucking pests.",
    ["Are the older, lower leaves yellowing first?", "Has the plant gone a long time without fertilizer or repotting?"],
    ["Consider a water-soluble fertilizer after fixing watering (Illinois)", "Repot into a larger container if root bound (Illinois)"],
    ["Check whether the plant is root bound"], loc=["lower_leaves_first"],
    caveats="Yellowing on older leaves can also come from poor root health, low light or sap-sucking pests.")
rec(UC, "micronutrient deficiency or soil pH imbalance", "nutrient", ["yellowing"],
    "Yellow-green newer leaves can be caused by overwatering, soil pH imbalance or micronutrient deficiency.",
    ["Is the yellowing on the newest leaves rather than the oldest?", "Has the soil been staying wet?"],
    ["Rule out overwatering first"], ["Compare new leaves with older leaves"], loc=["new_growth"],
    caveats="The source does not give specific tests for pH or micronutrients.")
rec(UC, "insufficient light", "environment", ["spindly_growth", "few_flowers", "yellowing"],
    "Leggy growth with long stems or petioles is usually caused by inadequate light. Lack of flowers can indicate inadequate light, and yellowing and leaf drop can also be caused by inadequate light.",
    ["Is the plant far from a window or in a dim room?", "Is new growth long, thin and stretched toward light?"],
    ["Move the plant closer to a light source or add artificial light"], ["Note how far the plant is from the nearest window"],
    parts=("whole_plant",), loc=["whole_plant"], caveats="Excess fertilizer can also cause spindly growth (UMD).")
rec(UC, "excess light (sunburn)", "environment", ["bleaching", "brown_spots"],
    "Excess light can bleach or whiten leaves and cause spots or blotches, especially after a recent move of the plant.",
    ["Was the plant recently moved into brighter light or outdoors?", "Is the damage on the side facing the window?"],
    ["Move the plant to a less sunny spot", "Acclimate plants slowly to higher light (UMD)"], ["Check which leaves get direct sun"],
    loc=["one_side"], caveats="Fungal and bacterial spots can look similar.")
rec(UC, "cold injury", "environment", ["blackening", "brown_spots"],
    "Chilling injury below 50°F can cause leaf spots and blackening of leaves or shoots. Symptoms may continue for up to a week after exposure.",
    ["Was the plant recently near a cold window, door or draft?", "Did temperatures drop below about 50°F?"],
    ["Protect plants from temperatures below 50°F", "Re-check in about a week, since symptoms can keep appearing"], ["Check where the plant sits at night"],
    loc=["whole_plant"])
rec(UC, "low humidity or drafty setting", "environment", ["browning"],
    "Brown leaf tips or margins may result from low relative humidity, too much sun or heat through a window, or a drafty setting, in addition to watering and fertilizer problems.",
    ["Is the plant near a heater, vent or drafty door?", "Is the air in the room very dry?"],
    ["Rule out watering and salt buildup first"], loc=["leaf_edges"], caveats="Erratic watering and drafts are also listed by Illinois as causes of brown edges.")
rec(ILL, "adjustment after moving", "environment", ["yellowing", "leaf_drop"],
    "Many plants go through an adjustment period anytime they are moved, even short distances. Yellowing or leaf drop that continues more than a few weeks suggests another problem.",
    ["Was the plant recently moved, repotted or brought home?", "Has it been more than a few weeks since the move?"],
    ["Give the plant a few weeks in favorable conditions", "If it continues, change its location and watering schedule"], loc=["whole_plant"],
    parts=("whole_plant",))
rec(UC, "pot-bound roots or compacted soil", "environment", ["yellowing", "leaf_drop", "wilting"],
    "Poor root health from pot-bound growth, compacted soil or poor drainage is listed as a cause of yellowing, leaf drop and sudden wilting.",
    ["Are roots circling the inside of the pot or coming out of the drainage holes?", "Has the soil become hard or compacted?"],
    ["Repot into fresh soil (Illinois)"], ["Slide the plant out of the pot to look at the roots"], parts=("root", "whole_plant"))
rec(UC, "spider mites", "pest", ["stippling", "webbing", "yellowing", "leaf_drop"],
    "Spider mites are tiny and usually on leaf undersides. Feeding causes light-colored specks (stippling), later bronzing and drying, and silk webbing may appear near growing points. Severe infestations cause leaves to dry and fall.",
    ["Is there fine webbing on or under the leaves?", "Do you see tiny pale specks on the leaves?"],
    ["Wash leaf surfaces with water frequently", "Reduce dust", "Dispose of infested plant parts", "Isolate the plant to prevent spread"],
    ["Look at leaf undersides, with a hand lens if you have one"], loc=["undersides"],
    caveats="Low humidity and dusty conditions favor mites. Thrips can cause similar stippling.")
rec(UC, "mealybugs", "pest", ["white_fluff", "sticky_residue", "yellowing", "wilting", "distorted_growth"],
    "Mealybugs are small, oval, whitish insects covered in cottony, powdery or waxy material, often along leaf veins or where leaf stalks join stems. Symptoms include stunted growth, yellowing and wilting; they excrete honeydew and attract ants.",
    ["Is there white cottony material in leaf joints or along veins?", "Are the leaves sticky?"],
    ["Wash or scrape them off", "Dab individual mealybugs with 70% or weaker rubbing alcohol on a cotton swab, testing a small area first", "Dispose of infested plant parts", "Isolate the plant"],
    ["Check crevices, leaf bases and flower clusters, and the roots"], parts=("leaf", "stem"),
    caveats="Rubbing alcohol is flammable. Heavy infestations may be best handled by discarding the plant.")
rec(UC, "aphids", "pest", ["visible_insects", "sticky_residue", "leaf_curl", "distorted_growth", "sooty_mold"],
    "Aphids are small insects on new growth or leaf undersides. They excrete sticky honeydew that can attract ants and encourage sooty mold, leave white cast skins, and can cause leaves to curl and distort.",
    ["Do you see small soft-bodied insects clustered on new growth?", "Are there white cast skins or sticky residue?"],
    ["Wash them off with a spray of water", "Remove, bag and dispose of infested plant parts", "Isolate the plant"],
    ["Check new growth and leaf undersides"], loc=["new_growth", "undersides"])
rec(UC, "scale insects", "pest", ["bumps_scale", "sticky_residue", "yellowing", "sooty_mold"],
    "Scales are small brown or grayish, mostly stationary insects with a waxy or hard covering. They suck sap and excrete honeydew, giving leaves a sticky surface and later stunting growth and discoloring leaves. On ferns they can resemble spore clusters.",
    ["Are there raised brown bumps on stems or leaves that can be scraped off?", "Are the leaves sticky?"],
    ["Scrape them off", "Wash off crawling young stages with water", "Dispose of heavily infested parts or the plant (Illinois)"],
    ["Check crevices, leaf bases and leaflet folds"], parts=("leaf", "stem"))
rec(UC, "whiteflies", "pest", ["visible_insects", "yellowing", "leaf_drop", "sticky_residue"],
    "Adult whiteflies are small white to yellowish winged insects that fly up when the plant is disturbed. Young stages stay on leaf undersides, suck sap and excrete honeydew, causing leaves to yellow and drop.",
    ["Do tiny white insects fly up when you touch the plant?", "Are there small immobile insects on leaf undersides?"],
    ["Wash eggs and crawling young off with water", "Dispose of infested plant parts", "Isolate the plant", "Yellow sticky traps may reduce adults"],
    ["Check leaf undersides"], loc=["undersides"], caveats="Large infestations may be best handled by discarding the plant.")
rec(UC, "thrips", "pest", ["stippling", "distorted_growth", "yellowing", "leaf_drop"],
    "Thrips are small slender insects usually on leaf undersides and in tight crevices. They cause scarring, sometimes distorted growth, stippling similar to mites, shiny black dots of excrement, and yellowing and dropping leaves; heavy infestations can leave silvery-gray areas.",
    ["Do you see shiny black dots on the leaves?", "Is the stippling accompanied by silvery-gray patches rather than webbing?"],
    ["Wash them off with water", "Dispose of infested plant parts"], ["Check leaf undersides and flowers"], loc=["undersides"],
    caveats="Thrips damage looks similar to spider mite stippling.")
rec(UC, "fungus gnats", "pest", ["visible_insects", "soil_wet", "wilting", "distorted_growth"],
    "Adult fungus gnats are small, dark, mosquito-like flies seen near potted plants or lights. Larvae in moist soil feed on roots; heavy infestations can cause sudden wilting, poor growth and foliage loss. Overwatering and poor drainage favor them.",
    ["Do small dark flies rise from the soil when you disturb it?", "Does the soil stay moist for long periods?"],
    ["Let the soil dry as much as possible between waterings", "Eliminate standing water", "Remove old plant debris", "Yellow sticky traps may trap adults"],
    ["Look at the soil surface and near windows or lights for adult flies"], parts=("soil", "whole_plant"))
rec(UC, "broad or cyclamen mites", "pest", ["distorted_growth", "leaf_curl", "few_flowers"],
    "Broad and cyclamen mites are nearly invisible and are recognized by injury on new growth: thickened, brittle foliage with stunted, downward-cupped margins. Cyclamen mites are mainly a pest of flowering plants and can cause few flowers.",
    ["Is the damage on the newest growth?", "Are leaf edges cupped downward and brittle?"],
    ["Frequently wash leaf surfaces with water", "Dispose of infested plant parts", "Cyclamen-mite infested plants are best discarded (UMD)"],
    ["Compare new growth with older leaves"], loc=["new_growth"],
    caveats="Chemical injury can cause similar symptoms, so mite damage is easily misidentified.")
rec(UC, "powdery mildew", "disease", ["powdery_coating"],
    "Powdery mildew shows as white to gray growth on leaves, flowers and stems; the growth is the fungus itself on the tissue surface. It usually will not kill the plant but can cause defoliation.",
    ["Does the white coating sit on the surface and look like powder?", "Is the plant in a humid spot with poor air flow?"],
    ["Improve air circulation", "Pick off infected leaves", "Reduce humidity by watering early in the day, moving to brighter light and away from cold drafts"],
    ["Check leaves, flowers and stems"], parts=("leaf", "stem", "flower"))
rec(UC, "gray mold (Botrytis)", "disease", ["fuzzy_mold"],
    "Gray mold mainly infects spent flowers and older foliage, appearing as grayish or tan areas with dusty gray spores. It needs high humidity for several hours and is usually not serious unless it stays cool and wet.",
    ["Is the fuzzy growth on old, faded flowers or older lower leaves?", "Has foliage stayed wet or the air been humid?"],
    ["Remove spent or infected flowers and foliage", "Increase air circulation and reduce humidity", "Avoid splashing water on foliage and flowers", "Water early in the day"],
    ["Check old flowers and lower leaves"], parts=("leaf", "flower"), loc=["lower_leaves_first"])
rec(UC, "fungal leaf spots", "disease", ["brown_spots"],
    "Fungal leaf spots are tan to reddish-brown to black, roughly circular spots that may merge into large lesions. They spread by splashing water and need hours of leaf wetness.",
    ["Are the spots roughly round with a defined edge?", "Has water been splashing onto the leaves?"],
    ["Avoid splashing water on foliage", "Water early in the day", "Remove and discard infected leaves promptly", "Improve air circulation"],
    ["Check both sides of spotted leaves"],
    caveats="UC IPM says foliar leaf spots are usually not a problem indoors; sunburn, chilling, overwatering and chemical injury cause similar spots.")
rec(UC, "bacterial leaf spot", "disease", ["water_soaked_spots", "brown_spots"],
    "Localized bacterial diseases appear as oily, greasy or water-soaked spots, often visible from the leaf underside, that may turn tan, brown or black with a yellow border and enlarge until the whole leaf is affected.",
    ["Do the spots look oily or water-soaked, especially from underneath?", "Do the spots have a yellow border?"],
    ["Lower humidity and keep plant surfaces dry", "Promptly remove infected parts", "Wash hands with soap and disinfect pruning tools in 70% alcohol after removing infected parts"],
    ["Look at leaf undersides and nearby stems"], loc=["undersides"])
rec(UC, "systemic bacterial stem rot or wilt", "disease", ["soft_stem_base", "wilting", "yellowing"],
    "Systemic bacterial diseases can cause wilting, general yellowing, and soft, mushy stem rots or cankers that may smell unpleasant. Control options are very limited and discarding the plant is often the best approach.",
    ["Is the stem soft or mushy, possibly with a bad smell?"],
    ["Avoid splashing water, contaminated hands and pruning tools", "Water sparsely and fertilize lightly", "Consider discarding the plant"],
    ["Check the stem base for soft, mushy tissue"], parts=("stem", "whole_plant"), caveats="Overwatering can also cause soft stem bases.")
rec(UMD, "stem canker", "disease", ["wilting"],
    "Stem cankers appear as discolored areas on the stem and can be associated with wilting.",
    ["Is there a discolored patch on the stem?"], ["Prune out affected areas"], ["Check stems for discolored areas"], parts=("stem",))
rec(UMD, "viral disease", "disease", ["mottling", "distorted_growth"],
    "Viruses cause foliage to appear mottled green and yellow, and plants may be stunted or distorted. There is no effective treatment.",
    ["Is the leaf color patchy green and yellow rather than evenly yellow?", "Is the plant also stunted or twisted?"],
    ["Discard infected plants", "Isolate the plant first"], ["Compare several leaves for the mottled pattern"],
    caveats="Aphids and mites can also cause stunted, distorted growth, so rule out pests.")
rec(UMD, "chewing pests from time outdoors", "pest", ["holes_chewing"],
    "Leaves that are eaten or chewed may be caused by pests on plants that spent the summer outside, such as caterpillars, leaf-feeding beetles, weevils, grasshoppers, crickets, slugs and earwigs.",
    ["Has the plant been outdoors recently?", "Are there ragged holes or chewed edges, possibly with droppings or slime?"],
    ["Handpick pests", "Repot plants before moving them inside"], ["Check the plant and soil for the chewing pest"])
rec(UC, "chemical or mechanical injury", "environment", ["browning", "brown_spots"],
    "Brown or scorched leaf tips and spots or blemishes can result from pesticide or mechanical injury, and chemical spray injury is listed as a cause of leaf spots.",
    ["Was the plant recently sprayed or bumped?"], [], ["Think back to recent sprays or handling"],
    caveats="Heavy mite feeding can leave plants vulnerable to injury from insecticidal sprays (UMD).")

# Phase 4 review sheet (human fills approve/edit/reject)
import csv
sheet = Path(__file__).resolve().parents[2] / "kb" / "records" / "review_sheet_batch1.csv"
with sheet.open("w", newline="") as f:
    w = csv.writer(f); w.writerow(["record_id", "cause", "symptoms", "summary", "source_url", "approve/edit/reject", "notes"])
    for r in R:
        w.writerow([r["record_id"], r["cause"], ";".join(r["symptoms"]), r["summary"], r["source_url"], "", ""])

out = Path(__file__).resolve().parents[2] / "kb" / "records" / "draft" / "houseplants_batch1.jsonl"
out.write_text("\n".join(json.dumps(r) for r in R) + "\n")
print(len(R), "records ->", out)
