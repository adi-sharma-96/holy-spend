import type { ExpenseItem } from "./types";

function browserLocale(locale: string): string {
  return locale.replace("_", "-");
}

export function humanizeToken(value: unknown, fallback = "Unavailable"): string {
  if (typeof value !== "string" || !value.trim()) return fallback;
  return value.split("_").join(" ");
}

export function money(
  amount: string | number | null | undefined,
  currency: string,
  locale = document.documentElement.lang || "en-CA",
): string {
  const value = Number(amount || 0);
  try {
    return new Intl.NumberFormat(browserLocale(locale), {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

export function compactDate(
  value: string | null | undefined,
  locale = document.documentElement.lang || "en-CA",
): string {
  if (!value) return "Date unavailable";
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return "Date unavailable";
  try {
    return new Intl.DateTimeFormat(browserLocale(locale), {
      month: "short",
      day: "numeric",
    }).format(parsed);
  } catch {
    return value;
  }
}

export function fullDate(
  value: string | null | undefined,
  locale = document.documentElement.lang || "en-CA",
): string {
  if (!value) return "Date unavailable";
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return "Date unavailable";
  try {
    return new Intl.DateTimeFormat(browserLocale(locale), {
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(parsed);
  } catch {
    return value;
  }
}

export function percent(value: string | number | null | undefined): string | undefined {
  if (value === null || value === undefined) return undefined;
  return `${Math.abs(Number(value)).toFixed(1)}%`;
}

export function decimal(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  try {
    return new Intl.NumberFormat(
      browserLocale(document.documentElement.lang || "en-CA"),
      {
        maximumFractionDigits: 6,
        useGrouping: false,
      },
    ).format(numeric);
  } catch {
    return String(numeric);
  }
}

export function itemName(item: ExpenseItem): string {
  return (
    item.variant_name ||
    item.concept_name ||
    item.interpreted_name ||
    item.normalized_name ||
    item.raw_name ||
    "Unnamed item"
  );
}

export type SizeFields = {
  quantity?: string | number | null;
  unit?: string | null;
  measured_value?: string | number | null;
  measured_unit?: string | null;
  package_value?: string | number | null;
  package_unit?: string | null;
  size_text?: string | null;
};

export function quantityLabel(item: SizeFields): string {
  const quantity = decimal(item.quantity);
  if (item.measured_value && item.measured_unit) {
    return `${decimal(item.measured_value)} ${item.measured_unit}`;
  }
  if (item.package_value && item.package_unit) {
    const prefix = quantity && Number(quantity) !== 1 ? `${quantity} × ` : "";
    return `${prefix}${decimal(item.package_value)} ${item.package_unit}`;
  }
  if (quantity) {
    return `${quantity}${item.unit ? ` ${item.unit}` : ""}`;
  }
  return item.size_text || "—";
}

export function unitPriceLabel(item: ExpenseItem, currency: string): string {
  if (item.unit_price_amount !== null && item.unit_price_amount !== undefined) {
    const basis =
      item.unit_price_basis_value && item.unit_price_basis_unit
        ? ` / ${decimal(item.unit_price_basis_value)} ${item.unit_price_basis_unit}`
        : item.unit
          ? ` / ${item.unit}`
          : "";
    return `${money(item.unit_price_amount, currency)}${basis}`;
  }
  if (item.normalized_unit_price_amount && item.normalized_unit) {
    return `${money(item.normalized_unit_price_amount, currency)} / ${item.normalized_unit}`;
  }
  return "—";
}

export function identityKey(item: ExpenseItem): string | undefined {
  if (item.variant_id) return `variant:${item.variant_id}`;
  if (item.concept_id) return `concept:${item.concept_id}`;
  if (item.normalized_name) return `name:${item.normalized_name}`;
  return undefined;
}
