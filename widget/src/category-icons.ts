import type { IconName } from "./icons";

export function categoryIcon(categorySlug: string): IconName {
  if (categorySlug === "adjustments.taxes_fees") return "receipt";
  const parts = categorySlug.split(".");
  const root = parts[0] || "";
  if (parts.includes("groceries")) return "basket";
  if (parts.includes("eating_out") || parts.includes("restaurants")) return "dining";
  if (root === "shopping_retail") return "bag";
  if (root === "transportation") return "car";
  if (root === "housing_utilities") return "home";
  if (root === "health_wellness" || root === "personal_care") return "heart";
  if (root === "travel") return "plane";
  if (root === "entertainment_leisure") return "play";
  return "sparkle";
}
