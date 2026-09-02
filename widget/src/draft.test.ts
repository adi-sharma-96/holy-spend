import { describe, expect, it } from "vitest";
import { draftFromSnapshot, emptyDraft, emptyItem, localIsoDate, savePayload } from "./draft";

describe("draft helpers", () => {
  it("creates a predictable empty manual draft", () => {
    const draft = emptyDraft(new Date("2026-07-27T12:00:00Z"));
    expect(draft.date).toBe("2026-07-27");
    expect(draft.currency).toBe("CAD");
    expect(draft.items).toEqual([]);
    expect(draft.adjustments).toEqual([]);
    expect(draft.notes).toBe("");
  });

  it("uses the browser's local calendar day, not the UTC day", () => {
    // toISOString() always normalizes to UTC, which silently rolls a manual
    // expense's default date to "tomorrow" for any user west of UTC once
    // it's late evening locally. localIsoDate must read local components.
    const now = new Date();
    const expected = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
      now.getDate(),
    ).padStart(2, "0")}`;
    expect(localIsoDate(now)).toBe(expected);
    expect(emptyDraft(now).date).toBe(expected);
  });

  it("preserves the server revision and receipt identity", () => {
    const draft = draftFromSnapshot({
      transaction: {
        id: "tx-1",
        status: "draft",
        source_type: "receipt",
        transaction_type: "expense",
        transaction_date: "2026-07-27",
        merchant_name_raw: "Market",
        notes: "Team lunch",
        currency: "CAD",
        fee_amount: "0.50",
        deposit_amount: "1.00",
        rounding_amount: "-0.01",
        total_amount: "12.50",
        updated_at: "2026-07-27T12:00:00Z",
        items: [
          {
            id: "item-1",
            raw_name: "Soup",
            category_slug: "dining",
            theme_slugs: [],
            quantity: "2",
            unit_price_amount: "5.00",
            line_total_amount: "10.00",
          },
        ],
        adjustments: [
          {
            id: "adjustment-1",
            type: "tip",
            subtype: null,
            amount: "2.50",
            description: "Server tip",
            raw_label: "Driver tip",
            affects_total: true,
            metadata: { printed: true },
          },
        ],
      },
      receipt: {
        receipt: { id: "receipt-1", transaction_id: "tx-1" },
        files: [],
      },
    });
    expect(draft.revision).toBe("2026-07-27T12:00:00Z");
    expect(draft.receiptId).toBe("receipt-1");
    expect(draft.notes).toBe("Team lunch");
    expect(draft.fee).toBe("0.50");
    expect(draft.deposit).toBe("1.00");
    expect(draft.rounding).toBe("-0.01");
    expect(draft.items[0]!.unitPrice).toBe("5.00");
    expect(draft.adjustments[0]).toEqual({
      itemIndex: undefined,
      type: "tip",
      subtype: "",
      amount: "2.50",
      description: "Server tip",
      rawLabel: "Driver tip",
      affectsTotal: true,
      metadata: { printed: true },
    });
  });

  it("does not put binary data or owner IDs into the save request", () => {
    const payload = savePayload(
      {
        ...emptyDraft(new Date("2026-07-27T12:00:00Z")),
        merchant: "Market",
        notes: "Keep the original",
        total: "12.50",
        items: [
          {
            ...emptyItem("dining"),
            name: "Soup",
            quantity: "2",
            unitPrice: "5.00",
            lineTotal: "10.00",
          },
        ],
        adjustments: [
          {
            type: "discount",
            subtype: "membership_benefit",
            amount: "2.50",
            description: "Member saving",
            rawLabel: "You saved",
            affectsTotal: false,
            metadata: { program: "member" },
          },
        ],
      },
      "request-123",
    );
    expect(JSON.stringify(payload)).not.toContain("user_id");
    expect(JSON.stringify(payload)).not.toContain("base64");
    expect(payload.client_request_id).toBe("request-123");
    expect(payload.draft).toMatchObject({
      notes: "Keep the original",
      items: [{ quantity: "2", unit_price_amount: "5.00" }],
      adjustments: [
        {
          type: "discount",
          subtype: "membership_benefit",
          amount: "2.50",
          affects_total: false,
          metadata: { program: "member" },
        },
      ],
    });
  });
});
