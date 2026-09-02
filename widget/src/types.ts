export type ToolResult = {
  content?: Array<{ type: string; text?: string }>;
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
  _meta?: Record<string, unknown>;
};

export type Category = {
  id: string;
  slug: string;
  stable_key?: string;
  name: string;
  is_assignable: boolean;
  level?: number;
  level_name?: string;
  path?: Array<{
    id: string;
    stable_key: string;
    level: number;
    level_name: string;
    name: string;
  }>;
};

export type ExpenseItem = {
  id?: string;
  raw_name?: string | null;
  interpreted_name?: string | null;
  normalized_name?: string | null;
  concept_id?: string | null;
  variant_id?: string | null;
  concept_name?: string | null;
  variant_name?: string | null;
  brand?: string | null;
  size_text?: string | null;
  category_slug?: string | null;
  taxonomy_node_id?: string;
  taxonomy_node_key?: string;
  taxonomy_node_name?: string;
  taxonomy_version?: string;
  taxonomy_path?: Category["path"];
  facet_value_keys?: string[];
  item_role?: "purchase" | "service" | "whole_bill";
  classification_source?: "user" | "alias" | "model" | "migration";
  classification_confidence?: string | number | null;
  classification_review_status?: "reviewed" | "suggested" | "needs_review";
  theme_slugs: string[];
  quantity?: string | number | null;
  unit?: string | null;
  measured_value?: string | number | null;
  measured_unit?: string | null;
  package_value?: string | number | null;
  package_unit?: string | null;
  unit_price_amount?: string | number | null;
  unit_price_basis_value?: string | number | null;
  unit_price_basis_unit?: string | null;
  normalized_unit?: string | null;
  normalized_unit_price_amount?: string | number | null;
  line_subtotal_amount?: string | number | null;
  line_discount_amount?: string | number | null;
  line_tax_amount?: string | number | null;
  line_fee_amount?: string | number | null;
  line_total_amount: string | number;
};

export type ExpenseAdjustment = {
  id?: string;
  item_id?: string | null;
  type: string;
  subtype?: string | null;
  amount: string | number;
  description?: string | null;
  raw_label?: string | null;
  affects_total: boolean;
  metadata: Record<string, unknown>;
};

export type ExpenseTransaction = {
  id: string;
  status: "draft" | "confirmed" | "void";
  source_type: string;
  transaction_type: string;
  classification_mode?: "itemized" | "whole_bill" | "mixed";
  ingestion_method?: "manual" | "receipt" | "email" | "provider_api" | "import";
  purchase_channel?: "in_store" | "online" | "delivery" | "subscription" | "unknown";
  provider_key?: string | null;
  transaction_date: string;
  merchant_name_raw?: string | null;
  merchant_name_normalized?: string | null;
  notes?: string | null;
  currency: string;
  subtotal_amount?: string | number | null;
  tax_amount?: string | number | null;
  fee_amount?: string | number | null;
  discount_amount?: string | number | null;
  tip_amount?: string | number | null;
  deposit_amount?: string | number | null;
  rounding_amount?: string | number | null;
  total_amount: string | number;
  reconciliation_delta_amount?: string | number | null;
  confirmed_at?: string | null;
  updated_at?: string | null;
  item_count?: number;
  // Dashboard/list responses intentionally return transaction summaries.
  // Full item arrays are only present after get_expense.
  items?: ExpenseItem[];
  adjustments?: ExpenseAdjustment[];
  validation_issues?: Array<{ severity: string; code: string; message: string }>;
};

export type ExpenseSnapshot = {
  transaction: ExpenseTransaction;
  receipt?: {
    receipt: { id: string; transaction_id: string };
    files: Array<{
      id: string;
      original_filename: string;
      mime_type: string;
      upload_status: string;
    }>;
  } | null;
};

export type DashboardPeriod = "month" | "30d" | "90d" | "year";

export type DashboardTotal = {
  currency: string;
  current_amount: string | number;
  previous_amount: string | number;
  delta_amount: string | number;
  delta_percent?: string | number | null;
};

export type DashboardCategory = {
  category_slug: string;
  category_name: string;
  taxonomy_level: number;
  taxonomy_level_name: string;
  has_children: boolean;
  currency: string;
  current_amount: string | number;
  previous_amount: string | number;
  delta_percent?: string | number | null;
  share_percent: string | number;
};

export type SpendTrendPoint = {
  period_start: string;
  label: string;
  currency: string;
  amount: string | number;
};

export type AnalyticsQueryResponse = {
  rows: Array<{
    dimensions: Record<string, string | null>;
    metrics: Record<string, string | number>;
  }>;
  confirmed_only: boolean;
};

export type PriceChange = {
  identity_key: string;
  label: string;
  taxonomy_key?: string | null;
  currency: string;
  normalized_unit: string;
  current_price: string | number;
  previous_price?: string | number | null;
  delta_amount?: string | number | null;
  delta_percent?: string | number | null;
  current_date: string;
  previous_date?: string | null;
  current_merchant?: string | null;
  previous_merchant?: string | null;
  best_price: string | number;
  best_date: string;
  best_merchant?: string | null;
  best_quantity_label?: string | null;
  comparison_price?: string | number | null;
  comparison_merchant?: string | null;
  savings_amount: string | number;
  savings_percent: string | number;
  sample_size: number;
  recent_prices?: Array<string | number>;
};

export type DashboardInsight = {
  kind: string;
  title: string;
  detail: string;
  tone: "neutral" | "positive" | "negative" | "attention" | string;
};

export type BasketProduct = {
  identity_key: string;
  label: string;
  merchant_name?: string | null;
  currency: string;
  normalized_unit: string;
  baseline_price: string | number;
  baseline_date: string;
  current_price: string | number;
  current_date: string;
  delta_percent: string | number;
  spend_amount: string | number;
  purchase_count: number;
};

export type PersonalBasketIndex = {
  currency: string;
  window_days: number;
  overall_delta_percent?: string | number | null;
  product_count: number;
  total_tracked_spend: string | number;
  covered_spend: string | number;
  coverage_percent: string | number;
  confidence: "high" | "low" | string;
  products: BasketProduct[];
};

export type MerchantSpend = {
  merchant_name: string;
  currency: string;
  current_amount: string | number;
  previous_amount: string | number;
  delta_percent?: string | number | null;
  share_percent: string | number;
  visit_count: number;
  average_amount: string | number;
};

export type MerchantBreakdownResponse = {
  window: {
    label: string;
    current_start: string;
    current_end: string;
    previous_start: string;
    previous_end: string;
  };
  currency: string;
  merchants: MerchantSpend[];
};

export type DailySpend = {
  spend_date: string;
  currency: string;
  amount: string | number;
  transaction_count: number;
};

export type ExpenseDashboard = {
  display_name?: string | null;
  default_currency: string;
  window: {
    label: string;
    current_start: string;
    current_end: string;
    previous_start: string;
    previous_end: string;
  };
  totals: DashboardTotal[];
  categories: DashboardCategory[];
  spend_trend: SpendTrendPoint[];
  daily_spend?: DailySpend[];
  insights: DashboardInsight[];
  recent_transactions: ExpenseTransaction[];
  needs_review_count: number;
  price_changes: PriceChange[];
  confirmed_only: boolean;
};

export type TransactionListResponse = {
  transactions: ExpenseTransaction[];
  total: number;
  limit: number;
  offset: number;
};

export type TrackerSection = "overview" | "transactions" | "trends" | "prices" | "nutrition";

export type ItemPricePoint = {
  transaction_id: string;
  transaction_item_id: string;
  transaction_date: string;
  merchant_name?: string | null;
  display_name: string;
  currency: string;
  normalized_unit: string;
  normalized_unit_price_amount: string | number;
  quantity?: string | number | null;
  unit?: string | null;
  measured_value?: string | number | null;
  measured_unit?: string | null;
  package_value?: string | number | null;
  package_unit?: string | null;
  line_total_amount: string | number;
};

export type ItemPriceHistory = {
  identity_key: string;
  label: string;
  series: Array<{
    currency: string;
    normalized_unit: string;
    points: ItemPricePoint[];
  }>;
};

export type NutritionItem = {
  transaction_item_id: string;
  identity_key: string;
  display_name: string;
  brand?: string | null;
  status: "pending" | "matched" | "no_match" | "error";
  purchase_count: number;
  nutriscore_grade?: string | null;
  nutriscore_source?: "computed" | "source_stated" | null;
  nova_group?: number | null;
  nova_group_estimated?: boolean;
  source?: string | null;
  source_ref?: string | null;
  spend_amount: string | number;
  energy_kcal_100g?: number | null;
  protein_100g?: number | null;
  fat_100g?: number | null;
  saturated_fat_100g?: number | null;
  trans_fat_100g?: number | null;
  carbohydrates_100g?: number | null;
  sugars_100g?: number | null;
  added_sugars_100g?: number | null;
  fiber_100g?: number | null;
  sodium_mg_100g?: number | null;
  cholesterol_mg_100g?: number | null;
  potassium_mg_100g?: number | null;
  calcium_mg_100g?: number | null;
  iron_mg_100g?: number | null;
  serving_size_g?: string | number | null;
  serving_label?: string | null;
};

export type NutritionCategoryGroup = {
  category_slug: string;
  category_name: string;
  items: NutritionItem[];
};

export type NutritionGradeBucket = {
  grade: string;
  spend_amount: string | number;
  share_percent: string | number;
};

export type NutritionSignal = {
  kind: string;
  title: string;
  detail: string;
  tone: "neutral" | "warn" | string;
};

export type NutritionSummary = {
  window: {
    label: string;
    current_start: string;
    current_end: string;
    previous_start: string;
    previous_end: string;
  };
  currency: string;
  overall_grade?: string | null;
  matched_item_count: number;
  total_item_count: number;
  coverage_percent: string | number;
  confidence: "high" | "low" | string;
  grade_distribution: NutritionGradeBucket[];
  signals: NutritionSignal[];
  groups: NutritionCategoryGroup[];
};

export type OpenAIExtension = {
  setWidgetState?: (state: Record<string, unknown>) => void;
  widgetState?: Record<string, unknown>;
  toolOutput?: Record<string, unknown>;
  toolInput?: Record<string, unknown>;
  toolResponseMetadata?: Record<string, unknown>;
  theme?: "light" | "dark";
  locale?: string;
  displayMode?: "inline" | "fullscreen" | "pip" | string;
  maxHeight?: number;
  safeArea?: { top?: number; right?: number; bottom?: number; left?: number };
  view?: unknown;
  userAgent?: string;
  requestDisplayMode?: (request: {
    mode: "inline" | "fullscreen" | "pip";
  }) => Promise<unknown>;
  requestModal?: (request: {
    params?: Record<string, unknown>;
    template?: string;
  }) => Promise<unknown>;
  requestClose?: () => Promise<unknown>;
};

export type HostContext = {
  theme?: "light" | "dark";
  locale?: string;
  displayMode?: "inline" | "fullscreen" | "pip" | string;
  availableDisplayModes?: Array<"inline" | "fullscreen" | "pip" | string>;
  containerDimensions?: {
    height?: number;
    maxHeight?: number;
    width?: number;
    maxWidth?: number;
  };
  platform?: "web" | "desktop" | "mobile";
  deviceCapabilities?: { touch?: boolean; hover?: boolean };
  userAgent?: string;
  safeAreaInsets?: { top?: number; right?: number; bottom?: number; left?: number };
};

declare global {
  interface Window {
    openai?: OpenAIExtension;
  }
}
