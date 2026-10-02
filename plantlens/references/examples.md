# Examples

These show the shape of good replies. The records and plant details here are placeholders for illustration; real answers must come from retrieved knowledge-base records, never from these examples.

---

## Example 1: Photo, plant unclear, problem visible

**Input:** photo of a leaf with yellowing between the veins and a few brown tips. No text.

**Observation object:**
```json
{
  "image_quality": "good",
  "plant": {"name": "unknown", "confidence": "low"},
  "plant_part": ["leaf"],
  "health": "possible_problem",
  "symptoms": ["yellowing", "brown_tips_edges"],
  "location_patterns": ["between_veins"],
  "extent": "few_leaves",
  "other_visible": []
}
```

**Reply (waiting on the user, so sections 1-4 only):**

**What I see:** A leaf with yellowing between the veins and a few brown, dry tips. Only a few leaves look affected in this photo.

**Plant:** I can't tell what plant this is from one leaf. What plant is it?

**Overall:** Possible problem.

**Questions:**
1. What plant is it?
2. Are the older, lower leaves affected first, or the new growth?
3. How soon after watering does the soil dry out?

I'll give possible causes once I know the plant, because the same symptoms mean different things on different plants.

---

## Example 2: Healthy plant

**Input:** photo of a whole plant with normal-looking leaves, one older lower leaf faded.

**Reply:**

**What I see:** The leaves look an even color with no spots, holes, curling, or coating. One older lower leaf is faded.

**Plant:** Looks like a pothos, medium confidence. Is that right?

**Overall:** Looks healthy.

One faded lower leaf can be normal aging, so I wouldn't treat it as a problem. Keep an eye on it: if more leaves fade over the next week or two, send another photo and tell me about watering and light.

*(No causes or checklist: there is no problem to explain, and inventing one would be wrong.)*

---

## Example 3: Full answer after the user replies, coverage good

**Context:** the user said it is a tomato, lower leaves yellow first, soil stays wet for days. Retrieved records (placeholders): overwatering, early blight, nitrogen deficiency.

**Reply:**

**What I see:** Yellowing starting on the lower leaves, with a few brown spots.

**Plant:** Tomato (you confirmed).

**Overall:** Possible problem.

**Possible causes** (possibilities, not a diagnosis):
1. **Watering stress** (watering): fits wet soil and lower-leaf yellowing. Less likely if the soil dries out within a day or two.
2. **Early blight** (disease): fits the brown spots on lower leaves. Check whether the spots have ring patterns; if not, this is less likely.
3. **Nitrogen shortage** (nutrient): fits uniform yellowing of older leaves. Less likely if spots are present.

**Next steps:**
- Check the roots and the drainage holes.
- Look at the undersides of affected leaves.
- Let the top of the soil dry before watering again.
- Remove badly affected leaves and keep them out of the compost.
- Re-check in 48 hours and send a new photo.

*Sources: records R12, R31, R44.*

---

## Example 4: Knowledge base does not cover it (coverage none)

**Reply:**

**What I see:** Distorted new growth with a sticky film on the leaves.

**Plant:** Looks like a houseplant, but I'm not sure which. Which one is it?

**Overall:** Possible problem.

My knowledge base does not have enough on this case to list causes I can source, so I'd rather not guess. Two things would help: is there anything on the undersides of the leaves (insects, bumps, webbing)? And how much light does the plant get?

For now: look closely at the undersides of the leaves and stems, and keep the plant apart from your other plants until you know more.

---

## Example 5: Poor photo

**Reply:** I can't tell much from this one. It's blurry and the plant is far away. Could you send a close, well-lit photo of the affected leaf, and one of the whole plant if you can?

---

## Example 6: Safety

**Input:** "My cat chewed on this plant. What is it and what's wrong with it?"

**Reply:** Since your cat chewed on it, knowing exactly what this plant is matters for safety. Some common houseplants are harmful to pets. I'd treat the identification as unconfirmed and contact your vet or a pet poison line, or a local expert, about the specific plant. If you tell me what you think it is, I can help describe what I see on the leaves in the meantime.
