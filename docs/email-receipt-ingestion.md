# Email receipt ingestion

Set up a recurring chat task that reads a dedicated forwarding inbox for
vendor receipt emails (Uber Eats, Amazon, Instacart, GoPuff, DoorDash,
Grubhub, Walmart, and any other vendor by extension) and writes them back
through the same Holy Spend connector used for manual receipts and
nutrition. No separate API key, no raw SQL.

Prerequisite: migrations `0026`–`0029`, their grant in
`supabase/bootstrap/001_runtime_role.sql` (re-run the bootstrap script if
this table was added after your initial setup — RLS policies alone don't
grant table access, the runtime role needs an explicit grant too), and the
four email-ingestion MCP tools (`check_emails_processed`,
`check_email_processed`, `claim_email_for_processing`,
`record_email_processed`) must already be live on your deployment.

## 1. Create a dedicated forwarding inbox

A new email address, separate from your primary inbox — the scheduled
task only ever sees this address, never your real correspondence. Set up
forwarding rules on your primary inbox for the vendors you want covered.

## 2. Connect Gmail to the scheduled-task host

This has been set up with Cursor's Gmail plugin (Plugins/MCP marketplace
→ Gmail → "Connect to Gmail via Google's remote MCP server"), authorized
against the dedicated inbox above, alongside the existing Holy Spend
connector in the same session.

## 3. Handle attachment-only receipts (optional)

Some vendors put pricing only in a PDF or image attachment, not the email
body — a Gmail connector generally exposes attachment metadata (filename,
mime type) but not the actual bytes, so the chat automation alone can't
read these. Two pieces close that gap, both optional — skip this section
and every attachment-only receipt just gets flagged for manual upload
instead (Step 3 of the prompt below), which is a fully supported fallback,
not a failure:

1. **[gmail-attachment-relay.gs](apps-script/gmail-attachment-relay.gs)** —
   a free Google Apps Script, run entirely on your own Google account, no
   third-party service, no cost. Copies each new email's real attachments
   into a Drive folder, named by that email's own Gmail message ID so the
   automation can find the right file deterministically. Runs on its own
   15-minute schedule, independent of the chat automation's cadence.
   Handles PDF, JPEG, PNG, and WebP — anything else copies to Drive fine
   but Holy Spend's own file ingestion only accepts those four types.
   Setup instructions are in the script's own header comment.
2. **A Google Drive connector on the scheduled-task host**, alongside the
   existing Gmail and Holy Spend connectors — needs to search files by
   name, read/download file content, and produce a shareable link. Exact
   tool names vary by platform, which is why the prompt below describes
   the capability rather than a specific tool name.

Prefer a hosted, no-code setup instead of a script? See
[email-attachment-relay-no-code.md](email-attachment-relay-no-code.md) for
a Make.com scenario doing the same relay, and the gotchas worth checking
by hand before trusting it.

## 4. Set up the scheduled task

Same shape as [nutrition automation](nutrition-automation.md): a
recurring trigger (cron or the platform's own scheduling UI), enough
per-run budget to process a batch (25 emails) without getting cut off
mid-run — nothing breaks if it does, the rest is just picked up next run.

## 5. The prompt

Paste this as the scheduled task's instructions. First replace the one
placeholder in it — `<your receipt-attachments Drive folder name>` in Step
3 — with the exact name of the Drive folder you set `DEST_FOLDER_ID` to
in [gmail-attachment-relay.gs](apps-script/gmail-attachment-relay.gs) (or
your no-code scenario's destination folder, if you used
[the Make.com alternative](email-attachment-relay-no-code.md) instead).
Skipped Step 3 entirely? Delete that whole paragraph instead of leaving
the placeholder in — an unresolved `<...>` left in the live prompt will
read as a literal folder name and just never match anything.

```
**Email receipt ingestion task — process new receipts from the dedicated forwarding inbox**

**Before doing anything else, on your very first run only**: confirm (a) you can read the full body content of an email in this inbox via the Gmail tool, not just subject/sender metadata, and (b) you can also see Holy Spend's tools (`check_emails_processed`, `check_email_processed`, `claim_email_for_processing`, `record_email_processed`, `save_expense_draft`, `create_receipt_draft_from_file`, `list_expenses`, `get_expense`) in this same session. If a tool call in this check is slow but still succeeds, that's a cold start on a scale-to-zero backend if hosted that way, not a failure — only treat it as broken if a call actually errors, or is slow and fails again on a single retry. If it's a genuine failure, stop and report exactly what failed instead of proceeding. Both have been confirmed working in real runs, so a failure here most likely means this specific session's connection needs a refresh, not a deeper problem — but confirm before proceeding regardless.

**Loop**: List emails in the inbox, then call `check_emails_processed` **once** with every message id from that listing (up to 25) — not one `check_email_processed` call per email, that's a round-trip per message for a question that has one answer. Only continue with the ids that come back `processed: false`. For each of those, before reading/classifying/drafting anything: call `claim_email_for_processing`. If it returns `claimed: false`, another attempt already owns this email (a duplicate scheduled run, or a still-in-flight attempt) — skip it entirely, don't process it. If `claimed: true`, proceed: decide the outcome (see below), act on it, then call `record_email_processed` with that outcome — **only once you've reached a real terminal outcome**. If a tool call genuinely errors (not "no data found," an actual failure) after a successful claim, don't call `record_email_processed` at all — the claim expires after an hour and the email is retried next run. Process up to 25 emails per run; leave the rest for next time.

(`check_email_processed`, singular, still exists for re-checking one message on its own — e.g. while troubleshooting a specific email — but the main loop should always use the batch form.)

Call `record_email_processed` with exactly one status:
- `drafted` — a transaction (new or updated) was saved for this email; pass its `transaction_id`.
- `flagged` — it's a real receipt needing itemization the email couldn't provide; pass a short `note` (no items shown, truncated item list, etc.), no draft created.
- `not_a_receipt` — not actually a purchase confirmation (marketing, a shipping-status update with no new pricing, etc.); no draft, no note needed.

**This inbox only ever receives forwarded receipts** — there's no need to filter by sender or vendor allowlist. If something forwarded here genuinely isn't a purchase receipt (a marketing email, a shipping-only status update with no pricing, anything that isn't a completed-purchase confirmation), record it as `not_a_receipt` and move on without drafting anything. Don't guess at a draft from an email that isn't actually a receipt.

**Never fabricate a tool call.** Every `save_expense_draft` call needs real values you actually read from the email or looked up — no invented order IDs, no guessed totals, no placeholder items. If you're not looking at real content, you don't have enough to draft; skip it (see the flag-for-review rule below) rather than filling gaps with a plausible-looking guess.

---

**Step 1 — decide itemized vs whole_bill.** This is content-based, not vendor-based, so it works for any vendor, not just the ones below:

- **Itemize** if the purchase falls under: groceries (`food_dining.groceries.*`), pharmacy (`health_wellness.pharmacy.*`), household supplies (`housing_utilities.household_operations.*`), pet supplies (`family_dependants_pets.pets.supplies`), or personal care (`personal_care.*`).
- **Whole_bill** for everything else — restaurants (`food_dining.eating_out.*`), shopping, transport, travel, subscriptions, utility/phone bills, and anything else.
- **When the email has no item list to classify** (most non-grocery receipts, and every Uber Eats email regardless of type), decide the category from the merchant name itself using your general knowledge of what kind of business it is — e.g. "FreshCo" is a grocery chain, "Paandian Vilas" is a restaurant, "Anthropic" is a software subscription. This is a judgment call, not a lookup table, so don't hesitate on a merchant you don't recognize by name — reason it out the same way you would when classifying an unfamiliar item.

**Step 2 — check for a duplicate before drafting anything.** Some vendors send more than one email per order (Amazon has up to 4 stages; Uber Eats can send a tip-added follow-up after the original receipt). Before calling `save_expense_draft`:
- If the email states an order/confirmation number, search recent same-merchant transactions via `list_expenses` and check each one's `receipt.receipt_number` (via `get_expense`) for a match. If one already exists, don't create a second transaction — record this email as `drafted` (with that existing `transaction_id`) and move on. (If the new email has materially better data than what's saved — e.g. this is the real order confirmation and the existing draft came from a thin follow-up — update it instead of skipping, using the same `transaction_id`.)
- If the email has no order number (Uber Eats never does), fall back to matching on merchant + the actual delivery/pickup timestamp from the email body — **not the total amount**, since Uber Eats can send a follow-up where the total itself changes (a tip-added email showed "Previous Total → New Total" for the same order in a real sample).

**Step 3 — if itemization is required but the data genuinely isn't there, don't partially draft.** Three real situations this covers:
- Uber Eats grocery orders never show items in the email at all, ever, regardless of pickup/delivery.
- A truncated item list — "See more items" (Instacart) or "Show all items" (Walmart) appearing anywhere in the email means you're not looking at the complete list.
- A subscription/bill whose amount isn't stated anywhere in the email body.

Don't try to fetch whatever's behind a "see more"/portal-login link — it almost certainly needs credentials you don't have.

If the email has a real attachment (a PDF or image, not an inline logo) and a Drive connector is available in this session, check it before flagging: search the Drive folder named `<your receipt-attachments Drive folder name>` for a file named `<this email's Gmail message ID>_*` (a separate always-on relay, outside this task, already copies real attachments there on its own schedule, named by message ID). If found, read its content to get the real itemized/total data, get its shareable download link, and use `create_receipt_draft_from_file` instead of `save_expense_draft` — pass the file's Drive download URL, file id, mime type, and name as the `file` parameter, plus the draft you built from what you actually read. This still goes through Step 5's validate/auto-confirm.

If no Drive connector is available in this session, or nothing matching turns up in the folder (the relay hasn't run yet, or genuinely has nothing for this vendor), fall back to flagging: note it for the end-of-run report as needing manual receipt upload (merchant, date, and why). This is a real record of a purchase we can't fully capture automatically, not an error — the owner already has a manual-upload workflow for exactly this.

**Step 4 — build the draft.**

For `whole_bill` mode: `classification_mode: "whole_bill"`, one item with `item_role: "whole_bill"` and `line_total_amount` equal to the full total. No further item detail needed.

For `itemized` mode: follow the exact same discipline already used for every other grocery item in this app — check `search_known_items` before finalizing each item's `normalized_name`/`brand` so repeat purchases merge into existing identities instead of fragmenting, capture size/brand/quantity from what the email states, and classify each item's `taxonomy_node_key` for real rather than reusing the order-level category guess. The category-recognition step in Step 1 tells you *whether* to itemize, not what each item's own taxonomy is.

Common fields for every draft:
- `source_type`: `"instacart"` for Instacart, `"uber_eats"` for Uber Eats, `"email"` for everything else (Amazon, DoorDash, Grubhub, GoPuff, Walmart, subscriptions — there's no dedicated enum value for these, generic `"email"` is correct).
- `ingestion_method`: `"email"`.
- `purchase_channel`: `"delivery"` for delivery orders, `"in_store"` for pickup orders (Walmart Pickup, Uber Eats self-pickup), `"subscription"` for recurring charges.
- `receipt.receipt_number`: the vendor's real order/confirmation number when the email states one (Amazon, Instacart if visible, Walmart, GoPuff) — leave null when it genuinely isn't there (Uber Eats), don't invent one.
- `merchant_name_raw`/`merchant_name_normalized`: as stated in the email.
- `transaction_date`: the actual purchase/order date from the email, not the date you're processing it.

**Step 5 — validate, then confirm.** Unlike every other automated path in this app, this task auto-confirms — that's an explicit, deliberate choice the owner made (and already applies the same way to their own interactive receipt uploads), not an oversight. After `save_expense_draft` (or `create_receipt_draft_from_file`, per Step 3) succeeds: call `validate_expense` on the transaction. If `confirmation_eligible` is true (no blocking issues), call `confirm_expense(transaction_id, explicit_approval=true)` immediately — don't wait for anyone, there's no one to wait for. If it's not eligible, leave it as a draft in the review queue rather than forcing it through.

One narrow exception, and it should be rare, not a routine gate: email receipts are retailer-generated text with full names already baked in ("Farm Boy™ Simply Five White Bread (700 g)") — nothing like a photographed paper receipt, where faded print or a cut-off edge makes brand/size genuinely illegible. So don't reach for this often. But on the rare item where even the full printed name doesn't give you a real brand or size (not "unfamiliar," genuinely absent from the text), treat it like Step 3's missing-data case: flag it for manual review rather than guessing and letting the guess get silently auto-confirmed. The bar is "the data itself doesn't resolve it," not "I don't recognize this brand."

When you do confirm, set `notes` on the draft to `"Auto-confirmed by scheduled email-ingestion task."` — so it's always possible to tell later which confirmed transactions came from this pipeline versus a real interactive review.

---

**Per-vendor notes** (from real samples — treat anything not listed here the same way, using the general rules above, since this is meant to generalize):

- **Instacart, Walmart Pickup, GoPuff** — full itemized data is normally right in the email body, no attachment needed. Instacart and Walmart both showed truncation on real orders even at moderate sizes ("See more items"/"Show all items") — check for this every time, don't assume a short-looking list is complete.
- **Amazon** — order number is always present (`702-XXXXXXX-XXXXXXX` format), use it for dedup per Step 2. Don't try to filter by which stage email this is (Ordered/Shipped/Delivered) — just check whether a transaction already exists for that order ID, and whether *this specific* email has pricing data before attempting to draft from it. Whether an Amazon item gets itemized is the normal Step 1 content judgment — a protein powder or household staple should itemize even though Amazon as a whole is mostly `whole_bill`.
- **DoorDash, Grubhub** — always `whole_bill` (restaurant), regardless of how complete the itemized data in the email looks. It doesn't feed anything that needs item-level detail.
- **Uber Eats (grocery, restaurant, pickup, delivery — all four behave the same)** — never itemized, no order number ever. Restaurant → draft as `whole_bill`. Grocery → skip and flag per Step 3, since the itemization this purchase actually needs isn't recoverable from the email.
- **Subscriptions/bills** (Claude, phone, internet, etc.) — always `whole_bill`. No real samples seen yet for this category, so if the total isn't obviously stated in the body, apply Step 3 rather than guessing.

---

**Once done, report:**
- How many transactions created, split by itemized vs whole_bill, with merchant + amount for each, and whether each was auto-confirmed or left as a draft because validation had blocking issues.
- How many itemized-draft items were flagged for ambiguous (not missing) brand/size rather than guessed.
- How many emails were skipped-and-flagged for manual review, with merchant + date + reason (no items available, truncated list, no amount found).
- How many were recognized as duplicates of an existing transaction (and whether any were updated rather than skipped).
- How many emails were recorded `not_a_receipt` — not actionable at all (marketing, status-only updates).
- Anything that didn't fit the rules above cleanly — flag it explicitly rather than silently forcing it into one of the categories, the same way you would for an unfamiliar grocery item.
```

## 6. Troubleshooting

**A tool call to `check_email_processed`/`check_emails_processed`/
`claim_email_for_processing`/`record_email_processed` fails with a generic "could not complete that
request" error, even though the tool itself shows up fine.** This is a
database permissions issue, not a connectivity one — Postgres row-level
security policies only filter rows *within* an already-granted operation,
they don't grant the operation itself. If `email_ingestion_log` (or any
new table added after your initial setup) isn't in the table list inside
`supabase/bootstrap/001_runtime_role.sql`, the runtime role has zero
access to it regardless of how correct the RLS policies are, and every
query throws a permission-denied error that the MCP layer reports
generically. Fix: add the table to that script's grant list and re-run it
against your database.

**Re-running the bootstrap script broke *everything*, not just the new
table.** The script resets the `expense_app` role's password on every
run, not just the first time — if you type anything other than the exact
password already baked into `DATABASE_URL` on your Railway services, the
app immediately loses all database access (both services show Online,
since the process itself didn't crash, but every request fails
authentication). Fix: re-run the script once more with the *correct*
original password, or update `DATABASE_URL` on both services to match
whatever you just set.

**`check_email_processed`/`check_emails_processed`/`claim_email_for_processing`/`record_email_processed`
not showing up at all.** Same
class of issue as nutrition's tool-list caching
([nutrition-automation.md](nutrition-automation.md#troubleshooting)) —
fully close and reopen the client before assuming the deploy failed.

**An email seems stuck and never gets retried, even though it was never actually drafted/flagged/recorded.** Almost certainly a message that got `claimed` (via `claim_email_for_processing`) and then the run died before calling `record_email_processed` — a crashed run, or the Holy Spend MCP connection dropping mid-processing. This self-heals: `check_emails_processed`/`check_email_processed` treat a `claimed` row as unprocessed again once it's more than an hour old, so the next run picks it back up on its own. No manual cleanup needed — just wait for the hour to pass, or don't worry about it at all since the next scheduled run usually is more than an hour later anyway.

**A vendor keeps creating duplicate transactions.** Check whether it
actually states an order/confirmation number in the email body. Uber Eats
never does, so it dedupes on merchant + delivery timestamp instead of an
order ID — if that's producing duplicates, the timestamp match is the
first thing to check.

**Items keep landing as `whole_bill` when they should itemize (or vice
versa).** The decision is content-based (taxonomy), not vendor-based —
check what category the item/merchant actually resolved to before
assuming the rule itself needs changing.

**An attachment-only receipt (Step 3) still gets flagged even though the
relay script is running.** Check three things in order: the Apps Script's
own Executions log (in the script editor) for whether it actually ran and
found the message; the Drive folder for a file actually named
`<message id>_1.<ext>` (a mismatched or missing message ID breaks the
lookup silently, it just won't match); and whether the scheduled-task host
actually has a Drive connector attached in the same session as Gmail and
Holy Spend — the prompt is written to degrade gracefully to flagging when
one isn't available, which looks identical to "the relay isn't working"
from the outside.

**`create_receipt_draft_from_file` fails on a file that looks fine in
Drive.** Most likely the file isn't actually the original bytes — a
no-code scenario (Make/Zapier) silently converted it to Google Docs format
on upload, which has no way to serve the original PDF/image back out. See
[email-attachment-relay-no-code.md](email-attachment-relay-no-code.md#gotchas-confirmed-by-hand-not-just-described)
if you're using one of those instead of the Apps Script relay. The Apps
Script version can't hit this failure mode — it never converts anything.
