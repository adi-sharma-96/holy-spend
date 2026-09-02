# Nutrition automation

Set up a recurring chat task that looks up nutrition facts for your
confirmed grocery items and writes them back through the same Holy Spend
connector you already use for receipts. No separate API key on the client
side, no raw SQL.

Prerequisite: migrations `0020`-`0025` and the 6 nutrition MCP tools,
including `search_nutrition_lookups` for correcting an already-matched
item ([self-hosting.md#nutrition](self-hosting.md#nutrition)), must
already be live on your deployment.

## 1. Add a USDA API key

Optional but recommended. Without it, the server falls back to USDA's
`DEMO_KEY`, rate-limited to roughly 30 requests/hour: fine for an
occasional run, a real bottleneck for clearing a large backlog.

1. Register for a free key at
   [fdc.nal.usda.gov/api-key-signup.html](https://fdc.nal.usda.gov/api-key-signup.html).
2. Set `USDA_FDC_API_KEY` on the `mcp` Railway service (the private one,
   not `api`) and redeploy.

## 2. Set up the scheduled task

Any host that supports both a recurring/scheduled agent session and the
Holy Spend connector will work. This has been used successfully with
Claude's scheduled tasks and Cursor's Automations feature. What it needs:

- The connector already set up, same as [Connect
  Claude](../README.md#step-3-connect-claude) or
  [ChatGPT](chatgpt-connection.md).
- A recurring trigger: cron, or the platform's own scheduling UI.
- Enough per-run budget to process at least one batch (25 items). A run
  that gets cut off mid-batch just leaves the rest for next time, nothing
  breaks.

**Cron runs in UTC, not your local timezone.** Convert before entering a
schedule. For example, 9:45am/9:45pm ET during EDT (UTC-4) is
`45 2,14 * * *`; during EST (UTC-5) it's `45 3,15 * * *`. Recheck twice a
year around the DST changeover, or the run will fire at the wrong local
time without any error to tell you.

**If the backend is hosted on a scale-to-zero platform** (Cloud Run's
free tier, for example — see
[gcp-cloud-run-deployment.md](gcp-cloud-run-deployment.md)), the very
first tool call of a run can be a few seconds slower than usual if the
service had gone idle - a cold start, not a broken connection. A single
slow-but-successful first call isn't a failure; only a call that
actually errors, or a slow call followed by a second failure on retry,
means the connection is genuinely down.

## 3. The prompt

Paste this as the scheduled task's instructions. It assumes
`nutrition_lookup_usda`, `nutrition_lookup_usda_detail`, and
`nutrition_lookup_off` are live (step 1's prerequisite). An older
deployment without them would need the source-priority section rewritten
around general web search instead.

```
**Nutrition lookup task — get nutritional facts for up to 25 items per run**

**Loop:** Call `get_nutrition_queue` with `limit: 25`. For each item, search using the source priority and plausibility rules below, then call `save_nutrition_result`. Repeat until the queue is empty or you're low on time — leave the rest for next run.

**Never fabricate a tool call.** `item_id` for `save_nutrition_result` must be copied verbatim from the `id` field of the specific item returned by `get_nutrition_queue` in this run — never invent, guess, reuse an id from memory, or pattern-generate one; if you don't have a real id in front of you, call `get_nutrition_queue` again rather than making one up. Same for every other argument: call the tool with no arguments first (or check its schema) if you're unsure what fields it actually accepts — `nutrition_lookup_off` only takes `query`, `barcode`, `page_size`, and `brand`; passing anything else will fail. `save_nutrition_result` takes a single `payload` object with the exact fields documented below — don't invent extra fields like `notes` or flatten the payload.

**Correcting an already-matched item:** if you notice (or are told) that an already-matched item's data is wrong, thin, or a source-stated grade with no real macros behind it, `get_nutrition_queue` won't help — it only ever returns pending/no_match rows. Call `search_nutrition_lookups` instead to find the item by name/brand and get its real `id`, then correct it the same way with `save_nutrition_result`.

**Use the built-in lookup tools, not your own scripts:** `nutrition_lookup_usda`, `nutrition_lookup_usda_detail`, and `nutrition_lookup_off` query USDA FoodData Central and Open Food Facts directly through Holy Spend and return nutrients already normalized to this app's per-100g fields (kcal/g/mg) — no API key needed on your end, no curl/Python required, no unit conversion to do yourself. Use these instead of building or reusing shell scripts. If your own automation notes already have a barcode or fdcId for this exact product from a previous run, call `nutrition_lookup_off(barcode=...)` or `nutrition_lookup_usda_detail(fdc_id=...)` directly rather than searching again.

**Automatic data-quality check:** every candidate these tools return has already been checked for internally-impossible macros (sugars exceeding carbs, saturated fat exceeding total fat, etc). If a candidate's `nutrients_per_100g` is `null` with a `data_quality_warning`, that candidate failed the check — don't use its numbers, move to the next candidate or source. This only catches internal inconsistency, not wrong-but-consistent data, and it does **not** catch a candidate that's mostly empty (see the Open Food Facts note below) — you still need to apply the plausibility check below on top of it.

**Source priority — search in this order, stop once you have a confident, *complete* match:**

1. **Official manufacturer or retailer page** for the exact branded product (e.g. `nakednutrition.com`, `catelli.ca`, `kraftheinz.com`; for Canadian grocery specifically, retailer product pages like `voila.ca`, `walmart.ca`, and `realcanadiansuperstore.ca` often have the full label, including for store-brand produce — e.g. Voila's own listing for "Compliments Gala Apples" carries a real per-item nutrition panel, not just generic produce data). Most trustworthy — this is the actual label. Use general web search/fetch for this tier.
   - Some retailer sites (Voila in particular) can return a blocked/404/403 response depending on session state — sometimes even a correct, working URL fails on one attempt and succeeds on the next with no change on your end. Treat a failed fetch as a genuine attempt-and-fail for this tier, not proof the page or data doesn't exist — retry once if your tooling allows it, and only move on if it still fails.

2. **Open Food Facts (`nutrition_lookup_off`) and MyNetDiary (mynetdiary.com) — treat as co-equal, not ranked against each other.** Both have proven reliable this account; neither strictly outranks the other. Search by product name (pass `brand` to `nutrition_lookup_off` to narrow noisy results, or use `barcode` directly if known); confirm the candidate's size/variant/flavor matches before trusting it. MyNetDiary has been notably strong for South Asian and other regional grocery items neither USDA nor OFF had any usable entry for at all (e.g. Handi-brand garlic paste, 777-brand idli chilli powder) — this account buys a meaningful number of items in that category, so don't skip straight past it to a generic aggregator. Whichever of the two gives you a complete, internally-consistent panel first is the one to use.
   - **Watch for a candidate that's mostly empty, from either source.** A real incident: an Open Food Facts entry had a stated Nutri-Score grade but every single macro field null except one suspiciously over-precise value (11.6071428571429g added sugars — that level of precision is itself a red flag, not a sign of accuracy). It got accepted because a stated grade alone technically satisfies the save requirement. **A stated grade only counts as sufficient if that same candidate's other fields aren't almost entirely null.** A grade with no real macro data behind it is a sign of bad data entry, not a usable minimal source — treat it as untrustworthy and keep searching, exactly as you would for a missing-fields case.

**A barcode you already know from a prior run is not a substitute for tier 2.** If your own notes/memory already have a barcode for a repeat item, an `nutrition_lookup_off(barcode=...)` hit is a fine shortcut for *Open Food Facts specifically* — but MyNetDiary has no barcode lookup, it only works by name search, so jumping straight to a remembered barcode means MyNetDiary never gets checked at all for that item. Do a quick MyNetDiary name search too before accepting a barcode-only match, exactly as you would if you had no barcode. And before accepting *any* barcode match (cached or freshly found), confirm the result's own `product_name` actually contains the item's real brand and product text — a barcode match that comes back with a generic name like "Eggs" or "Baby Spinach" instead of "Conestoga Farms Free Run Omega-3 Eggs" or "Compliments Baby Spinach" is a sign the barcode is tied to the wrong or a mismatched community entry, not proof it's the right product. If the name doesn't match, don't save it — search again by name instead.

3. **USDA FoodData Central**, via `nutrition_lookup_usda` — **reserve this for unbranded/generic items only** (produce, raw spices, basic dairy, plain meat/grains). It's the best, most authoritative source for those. Don't reach for USDA's `Branded` data_type for something with a real brand or packaging — its branded coverage and serving-size data are thin for this account's actual purchase mix; try tier 1 or 2 for anything branded instead. When you do use it for a generic item, pass `data_types` to narrow noisy results (`["Foundation", "SR Legacy"]` for a raw whole food, `["Survey (FNDDS)"]` for a prepared/bakery generic).

4. **Other secondary aggregators** (FatSecret, eatthismuch.com, Recipal) — last resort, once tiers 1–3 are exhausted. If a number from one of these looks unusual, cross-check it against a second source before reporting it.

**When sources disagree, or a higher tier is incomplete:** prefer whichever gives you a complete, internally-consistent 6-field panel over one that's technically higher-tier but thin or partial. Tier order is a starting search order, not a rule that a higher tier always wins once you actually have the data in front of you.

**Matching precision:** match on brand + product name + size/variant together, not just a loose keyword match. "Chalo Unripened Paneer 300g" and a generic "Paneer" search should both resolve to the same real product if they're the same item — don't let small differences in how the item was scanned lead you to different, lower-quality sources for what's actually the identical purchase.

If the item name looks like OCR noise or a truncated label rather than a real product name, use your best judgment on what product it actually represents before searching — don't search the literal garbled text.

Before reporting a no-match, try at least 2–3 different search phrasings — with and without brand, the generic ingredient name alone, and an anglicized/translated name if the product name looks non-English. A single failed search isn't enough to conclude nothing exists.

**Plausibility check — do this before reporting any value, not after:** ask whether the number makes sense for *this specific food category*. A dry spice or powder with double-digit sugar per 100g, a raw vegetable with more fat than a nut, a beverage denser than syrup — these are signs the source got scraped wrong or matched to the wrong product, not real values. If something looks off, find a second source to confirm or replace it rather than reporting the suspicious figure as-is. Also check that your `source` name and `source_ref` URL actually correspond to each other and to the product — a mismatch between them (stating one site, linking to a different one) is itself a red flag that something went wrong upstream.

**What to collect, per field:**
- Energy, protein, fat, saturated fat, trans fat, carbohydrates, sugars, added sugars, fiber, sodium, cholesterol, potassium, calcium, iron — report only what the source *states*, never a recalled or estimated number, for every one of these without exception. `added_sugars_g` ≠ `sugars_g` — don't conflate them; only report added sugars when the label states it separately.
- `basis`/`serving_size_g` — report per-100g when the source shows it, otherwise per-serving with the real serving size; never convert the units yourself.
- **`serving_label`** — when the source shows an explicit serving-based breakdown (e.g. "2 tbsp (30 mL)", "1 slice (28g)"), report it using the source's own wording alongside `serving_size_g`, even when you're also reporting `basis: "per_100g"` as the main values — this is purely an informational display field, never invent one for a source that only gives per-100g values with no separate serving mentioned.
- The server hard-rejects a few physically impossible combinations (sugars > carbs, saturated fat > total fat) at save time too. If `save_nutrition_result` errors on that, it means the source's numbers were internally inconsistent — find a better source, don't force one number down to make it pass.
- `nutriscore_grade` — only when the source explicitly shows a Nutri-Score badge/letter. The app computes its own from your reported macros and prefers that when it can; don't try to compute or guess one yourself. See the tier-2 note above before treating a stated grade alone as enough.
- `nova_group` — report a source-stated value with `nova_group_estimated: false`, or your own estimate from the ingredient list with `nova_group_estimated: true` when no source states one. This is the one field where estimation is explicitly allowed.

**No trustworthy source found:** report a no-match rather than a low-confidence guess.

**Before calling `save_nutrition_result` with `matched: true`:** you need either a source-stated `nutriscore_grade` (from a candidate that isn't otherwise almost-entirely-null — see above) or **all 6** of these fields: energy, sugars, saturated fat, sodium, fiber, protein — a partial subset isn't enough, since scoring needs every one of them. If your best source is missing just one or two, don't stop there and don't give up on the item: search again with different keywords (a more specific product name, the brand's own site, a different retailer's nutrition panel, or the other tier-2 source) to find the missing field before falling back to a lower-tier source or a no-match. Reasonable confidence in the found value is fine — it doesn't need to be from the exact same page as the rest, as long as it's genuinely the same product/variant. A match missing even one required field with no grade stated will be **rejected by the tool** — if that happens, don't just resubmit the same thin data, go find the missing piece or report a no-match instead.

**Once done:** always report how many matched, how many didn't match, how many are left in the queue, and any other important stats from the run. Make sure this report accurately reflects what you actually saved via `save_nutrition_result` — don't describe an item as "no-match" in the summary if you actually called it matched (or vice versa); the report and the real tool calls must agree.
```

## 4. What to expect from the first run

A full backlog rarely clears in one run: it stops when it runs low on
time or context, not when the queue is empty, and just picks up where it
left off next scheduled run. 50-60 items typically takes 2-3 runs to
clear once the model settles into a rhythm.

## Model choice

The built-in lookup tools do most of the mechanical work (searching,
unit conversion, macro-consistency checks), so the model's job is mostly
judgment: is this candidate plausible, is it the right product, does the
name/brand match. A mid-tier model is usually enough; save a top-tier one
for when you're troubleshooting a batch of stubborn no-matches.

## Troubleshooting

**The client shows fewer tools than expected after a deploy.** Some
hosts cache their tool list independently of what a "reload" or
"reconnect" button does. Fully close and reopen the client before
assuming the deploy failed.

**A lot of matched items never get a Nutri-Score grade.** Check
`get_nutrition_summary`'s `grade_distribution` for a large "unknown"
share. That means matches are landing without a source-stated grade or
all 6 core macros more often than expected. The completeness gate
described in [self-hosting.md#nutrition](self-hosting.md#nutrition)
should already reject those at save time, so a lot of them getting
through anyway usually means the deployed code is stale, not that the
gate needs loosening.

**The same real product shows up as two separate tiles.** Nutrition
identity is `(normalized_name, brand, category)`. If the same product
was scanned with different wording across two receipts, it fragments.
The main server instructions already tell the receipt-extraction model
to check purchase history and reuse existing naming before finalizing a
new item, which prevents this for new purchases going forward. A
duplicate that already exists needs a one-off manual correction (align
the two items' `normalized_name`/`brand` through `correct_confirmed_expense`).
There's no bulk merge tool for this yet.
