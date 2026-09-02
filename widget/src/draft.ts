import type { ExpenseSnapshot, ExpenseTransaction } from "./types";

export type DraftItem = {
  name: string;
  brand: string;
  categorySlug: string;
  quantity: string;
  unit: string;
  measuredValue: string;
  measuredUnit: string;
  packageValue: string;
  packageUnit: string;
  unitPrice: string;
  unitPriceBasisValue: string;
  unitPriceBasisUnit: string;
  lineTotal: string;
};

export type DraftForm = {
  transactionId?: string;
  revision?: string;
  receiptId?: string;
  date: string;
  merchant: string;
  notes: string;
  currency: string;
  subtotal: string;
  tax: string;
  fee: string;
  discount: string;
  tip: string;
  deposit: string;
  rounding: string;
  total: string;
  items: DraftItem[];
  adjustments: Array<{
    itemIndex?: number;
    type: string;
    subtype: string;
    amount: string;
    description: string;
    rawLabel: string;
    affectsTotal: boolean;
    metadata: Record<string, unknown>;
  }>;
};

export function emptyItem(categorySlug = ""): DraftItem {
  return {
    name: "",
    brand: "",
    categorySlug,
    quantity: "1",
    unit: "each",
    measuredValue: "",
    measuredUnit: "",
    packageValue: "",
    packageUnit: "",
    unitPrice: "",
    unitPriceBasisValue: "",
    unitPriceBasisUnit: "",
    lineTotal: "",
  };
}

/** Formats a Date as its LOCAL calendar day, not the UTC day toISOString() would give. */
export function localIsoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function emptyDraft(today = new Date()): DraftForm {
  return {
    date: localIsoDate(today),
    merchant: "",
    notes: "",
    currency: "CAD",
    subtotal: "",
    tax: "",
    fee: "",
    discount: "",
    tip: "",
    deposit: "",
    rounding: "",
    total: "",
    items: [],
    adjustments: [],
  };
}

function text(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

export function draftFromSnapshot(snapshot: ExpenseSnapshot): DraftForm {
  const transaction = snapshot.transaction;
  return {
    transactionId: transaction.id,
    revision: transaction.updated_at || undefined,
    receiptId: snapshot.receipt?.receipt.id,
    date: transaction.transaction_date,
    merchant: transaction.merchant_name_raw || transaction.merchant_name_normalized || "",
    notes: transaction.notes || "",
    currency: transaction.currency,
    subtotal: text(transaction.subtotal_amount),
    tax: text(transaction.tax_amount),
    fee: text(transaction.fee_amount),
    discount: text(transaction.discount_amount),
    tip: text(transaction.tip_amount),
    deposit: text(transaction.deposit_amount),
    rounding: text(transaction.rounding_amount),
    total: text(transaction.total_amount),
    items: (transaction.items || []).map((item) => ({
      name: item.raw_name || item.interpreted_name || item.normalized_name || "",
      brand: item.brand || "",
      categorySlug: item.taxonomy_node_key || item.category_slug || "",
      quantity: text(item.quantity),
      unit: item.unit || "",
      measuredValue: text(item.measured_value),
      measuredUnit: item.measured_unit || "",
      packageValue: text(item.package_value),
      packageUnit: item.package_unit || "",
      unitPrice: text(item.unit_price_amount),
      unitPriceBasisValue: text(item.unit_price_basis_value),
      unitPriceBasisUnit: item.unit_price_basis_unit || "",
      lineTotal: text(item.line_total_amount),
    })),
    adjustments: (transaction.adjustments || []).map((adjustment) => ({
      itemIndex: adjustment.item_id
        ? (transaction.items || []).findIndex((item) => item.id === adjustment.item_id)
        : undefined,
      type: adjustment.type,
      subtype: adjustment.subtype || "",
      amount: text(adjustment.amount),
      description: adjustment.description || "",
      rawLabel: adjustment.raw_label || "",
      affectsTotal: adjustment.affects_total,
      metadata: adjustment.metadata,
    })),
  };
}

export function draftFromEditableDraft(value: Record<string, unknown>): DraftForm {
  const items = Array.isArray(value.items) ? value.items as Array<Record<string, unknown>> : [];
  const adjustments = Array.isArray(value.adjustments)
    ? value.adjustments as Array<Record<string, unknown>>
    : [];
  return {
    date: text(value.transaction_date),
    merchant: text(value.merchant_name_raw || value.merchant_name_normalized),
    notes: text(value.notes),
    currency: text(value.currency) || "CAD",
    subtotal: text(value.subtotal_amount),
    tax: text(value.tax_amount),
    fee: text(value.fee_amount),
    discount: text(value.discount_amount),
    tip: text(value.tip_amount),
    deposit: text(value.deposit_amount),
    rounding: text(value.rounding_amount),
    total: text(value.total_amount),
    items: items.map((item) => ({
      name: text(item.raw_name || item.interpreted_name || item.normalized_name),
      brand: text(item.brand),
      categorySlug:
        text(item.taxonomy_node_key || item.category_slug)
        || "unclassified.needs_review",
      quantity: text(item.quantity),
      unit: text(item.unit),
      measuredValue: text(item.measured_value),
      measuredUnit: text(item.measured_unit),
      packageValue: text(item.package_value),
      packageUnit: text(item.package_unit),
      unitPrice: text(item.unit_price_amount),
      unitPriceBasisValue: text(item.unit_price_basis_value),
      unitPriceBasisUnit: text(item.unit_price_basis_unit),
      lineTotal: text(item.line_total_amount),
    })),
    adjustments: adjustments.map((adjustment) => ({
      itemIndex: typeof adjustment.item_index === "number" ? adjustment.item_index : undefined,
      type: text(adjustment.type),
      subtype: text(adjustment.subtype),
      amount: text(adjustment.amount),
      description: text(adjustment.description),
      rawLabel: text(adjustment.raw_label),
      affectsTotal: adjustment.affects_total !== false,
      metadata:
        adjustment.metadata && typeof adjustment.metadata === "object"
          ? adjustment.metadata as Record<string, unknown>
          : {},
    })),
  };
}

function optionalValue(value: string): string | undefined {
  const candidate = value.trim();
  return candidate ? candidate : undefined;
}

export function savePayload(form: DraftForm, clientRequestId: string): Record<string, unknown> {
  return {
    draft: {
      source_type: form.receiptId ? "receipt" : "manual",
      transaction_type: "expense",
      classification_mode: form.receiptId || form.items.length > 1 ? "itemized" : "whole_bill",
      ingestion_method: form.receiptId ? "receipt" : "manual",
      purchase_channel: "unknown",
      transaction_date: form.date,
      merchant_name_raw: form.merchant.trim() || undefined,
      merchant_name_normalized: form.merchant.trim() || undefined,
      notes: form.notes.trim() || undefined,
      currency: form.currency,
      subtotal_amount: optionalValue(form.subtotal),
      tax_amount: optionalValue(form.tax),
      fee_amount: optionalValue(form.fee),
      discount_amount: optionalValue(form.discount),
      tip_amount: optionalValue(form.tip),
      deposit_amount: optionalValue(form.deposit),
      rounding_amount: optionalValue(form.rounding),
      total_amount: form.total,
      receipt: form.receiptId ? {} : undefined,
      items: form.items.map((item) => ({
        raw_name: item.name.trim() || undefined,
        interpreted_name: item.name.trim() || undefined,
        normalized_name: item.name.trim().toLowerCase() || undefined,
        brand: optionalValue(item.brand),
        taxonomy_node_key: item.categorySlug,
        item_role: !form.receiptId && form.items.length === 1 ? "whole_bill" : "purchase",
        classification_source: "user",
        classification_review_status: "reviewed",
        facet_value_keys: [],
        theme_slugs: [],
        quantity: optionalValue(item.quantity),
        unit: optionalValue(item.unit),
        measured_value: optionalValue(item.measuredValue),
        measured_unit: optionalValue(item.measuredUnit),
        package_value: optionalValue(item.packageValue),
        package_unit: optionalValue(item.packageUnit),
        unit_price_amount: optionalValue(item.unitPrice),
        unit_price_basis_value: optionalValue(item.unitPriceBasisValue),
        unit_price_basis_unit: optionalValue(item.unitPriceBasisUnit),
        line_total_amount: item.lineTotal,
      })),
      adjustments: form.adjustments.map((adjustment) => ({
        item_index:
          adjustment.itemIndex !== undefined && adjustment.itemIndex >= 0
            ? adjustment.itemIndex
            : undefined,
        type: adjustment.type,
        subtype: optionalValue(adjustment.subtype),
        amount: adjustment.amount,
        description: adjustment.description.trim() || undefined,
        raw_label: adjustment.rawLabel.trim() || undefined,
        affects_total: adjustment.affectsTotal,
        metadata: adjustment.metadata,
      })),
    },
    transaction_id: form.transactionId,
    expected_revision: form.transactionId ? form.revision : undefined,
    client_request_id: clientRequestId,
  };
}

export function transactionFromUnknown(value: unknown): ExpenseTransaction | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const candidate = value as Record<string, unknown>;
  if (candidate.transaction && typeof candidate.transaction === "object") {
    return candidate.transaction as ExpenseTransaction;
  }
  return undefined;
}
