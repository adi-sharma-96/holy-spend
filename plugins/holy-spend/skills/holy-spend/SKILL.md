---
name: holy-spend
description: Use the connected self-hosted Holy Spend tracker to extract receipts, create or edit expense drafts, validate and explicitly confirm them, browse history, or analyze confirmed spending. Trigger for receipts, purchases, expenses, spending, merchant history, categories, discounts, taxes, tips, refunds, and personal expense analytics.
---

# Holy Spend

Use the connected tools as a private, single-owner expense tracker. The server
resolves the owner; never ask for, invent, or pass a user ID.

## Choose the workflow

- For a receipt image or PDF attached in chat, ChatGPT is the only extraction engine. Visually inspect it, then call `create_receipt_draft_from_file` once with the same file and a complete meaningful GPT-produced candidate. The tool atomically verifies the file, prevents exact-file duplicates, stores the original, and creates or replays the reviewable draft without opening UI.
- For a purchase without a receipt, use the manual-entry editor or save a manual draft directly.
- For corrections, load the current confirmed expense, preserve its latest revision, present the complete replacement and reason, then use `correct_confirmed_expense` only after explicit approval.
- For history and analytics, use the read tools without opening UI unless an interactive view would help.

## Receipt extraction

1. Visually read the attached receipt in ChatGPT. Never ask the backend to OCR, parse, infer, or classify receipt contents.
2. Read `get_taxonomy_manifest` once per taxonomy version. Use
   `get_taxonomy_branch` after identifying a broad domain and
   `search_taxonomy` for ambiguous lines. Never invent a taxonomy key.
3. Use `resolve_expense_aliases` for merchant and raw item names. Prefer an
   owner-specific resolution when available; do not fabricate an alias. An
   alias is a suggestion and does not replace taxonomy compatibility checks.
4. Preserve the raw merchant and item text. Add normalized or interpreted names separately.
5. Extract, when visible: transaction date, merchant, currency, receipt number,
   items, quantities, measured weight or volume, repeated package size, printed
   unit-price basis, unit prices, line subtotals, line discounts, taxes, fees,
   deposits, tip, rounding, and final total.
6. Store exact adjustment `raw_label` values and use only the supported fee/discount subtypes. Use `affects_total: false` for informational savings that are not part of the printed arithmetic. When printed item prices are already net of discounts, values such as `YOU SAVED` or `TOTAL SAVINGS` are informational and must not be subtracted again.
7. Do not guess unreadable values. Leave optional values absent and surface uncertainty for review.
8. Classify every semantic line with `taxonomy_node_key` using an assignable
   active leaf compatible with the transaction type. Use `itemized` for
   receipts with product/service lines, `whole_bill` with exactly one semantic
   line for non-itemized bills, and `mixed` only when both structures are
   genuinely present.
9. Put attributes such as fresh/frozen, vegan, local, recurring, essential,
   audience, and sale format in `facet_value_keys`. Do not multiply taxonomy
   branches for these attributes. Legacy category/theme fields are
   compatibility projections, not the write contract.
10. Treat total-affecting coupons and discounts as negative contributions; taxes, fees, deposits, tips, and positive rounding as positive contributions. Preserve refunds as refunds rather than converting them into expenses.
11. If the candidate has a positive total and either a merchant or meaningful line items, call `create_receipt_draft_from_file` once with the attached OpenAI file object, the complete draft, and a stable `client_request_id`. Do not create an empty or headless candidate.
12. The tool result is authoritative. It either creates one reviewable draft or replays the existing transaction for identical receipt bytes. Do not retry with a new request ID merely because the same transaction already exists.
13. The tool is data-only. Keep saving, validation, and confirmation in chat unless the user explicitly asks to open, review, edit, or view the tracker.
14. If the user explicitly requests interactive review, call `open_expense_tracker` once with `/expenses/{transaction_id}/review`. This is the same main tracker, not a separate editor.
15. Use `save_expense_draft` for subsequent draft edits with a stable `client_request_id` and the exact latest `expected_revision`.

Receipt bytes must use the declared OpenAI file parameter on
`create_receipt_draft_from_file`. Never serialize base64 receipt bytes into
ordinary JSON arguments or tool results. Never repeat or persist temporary
download URLs.

Receipt upload inside the widget is intentionally unsupported. If the user
wants to scan a receipt, ask them to attach it directly in chat. The widget
supports manual entry, review, confirmation, history, analytics, corrections,
deletion, receipt viewing, and price history.

## Validate and confirm

Saving is not confirmation.

1. Call `validate_expense` after the draft is saved.
2. Present merchant, date, currency, subtotal, tax, each fee, each discount or
   informational benefit, tip, total, important line items, uncertainty, and
   blocking/warning issues.
3. Resolve blocking issues and validate again.
4. Call `confirm_expense` with `explicit_approval: true` only after the user clearly approves the reviewed expense. An explicit request to save and confirm in the same message counts as approval once validation has no blocking issues.
5. Never infer approval from uploading a file, asking for extraction, saving a draft, or requesting validation.

Confirmed corrections are separate from draft saves. Present the changed values and correction reason, obtain explicit approval, then call `correct_confirmed_expense` with the latest `expected_revision`. A successful correction remains confirmed, is revalidated atomically, and is audit logged.

Deletion also requires a clear user request. Pass `explicit_confirmation: true` only after that request, and identify what will be permanently removed.

## History and analytics

- Use `list_expenses` for filtered history and `get_expense` for full detail.
- Use `get_expense_dashboard` for the focused overview: period comparisons,
  level-2 spending-group shares, drafts needing review, recent activity, and
  useful signals. `Needs Review` is workflow state, never a spend group.
- The interactive overview starts at level 2 (`Group`), drills one taxonomy
  level per selection, and shows the full path plus assignable leaf on
  transaction line items.
- Use taxonomy rollup levels 1–6 for semantic drill-down. Use facets for
  cross-cutting attributes and ingestion method, purchase channel, or provider
  for origin questions.
- Use `get_item_price_history` only with a stable concept, variant, or normalized
  name identity.
- Analytics includes confirmed transactions only.
- Never combine monetary values from incompatible currencies. Keep the implicit currency dimension, or filter to one currency.
- Never describe two item prices as comparable unless both currency and
  normalized unit match. Preserve the receipt's original unit in the detail.
- State the time range, filters, metric, and grouping used for a result.
- Distinguish purchase counts, quantities, and monetary totals.

## Interactive views

- `open_expense_tracker` is the only render tool. Use it only when the user
  explicitly asks to open, review, edit, or browse the focused overview, manual
  entry, recent history, price watch, transaction detail, or review route.
- `create_receipt_draft_from_file` is data-only and never mounts an iframe.
  For explicit receipt review, call `open_expense_tracker` with
  `/expenses/{transaction_id}/review` after the draft is saved.
- Data and mutation tools remain usable without UI. If the user asks a
  chat-only question or explicitly requests chat-only handling, do not open the
  interactive view unnecessarily.

The data tools remain authoritative. Widget state is temporary presentation state and must not replace a saved server draft.
