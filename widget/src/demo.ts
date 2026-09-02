import type {
  Category,
  ExpenseDashboard,
  ExpenseSnapshot,
  ItemPriceHistory,
  MerchantBreakdownResponse,
  NutritionSummary,
  PersonalBasketIndex,
  ToolResult,
} from "./types";
import { localIsoDate } from "./draft";
import { TAXONOMY_V2 } from "./taxonomy.generated";

const transactionA: ExpenseSnapshot = {
  transaction: {
    id: "11111111-1111-4111-8111-111111111111",
    status: "confirmed",
    source_type: "receipt",
    transaction_type: "expense",
    transaction_date: "2026-07-26",
    merchant_name_raw: "Farm Boy",
    merchant_name_normalized: "Farm Boy",
    notes: "Weekly groceries",
    currency: "CAD",
    subtotal_amount: "54.17",
    tax_amount: "2.11",
    total_amount: "56.28",
    reconciliation_delta_amount: "0",
    updated_at: "2026-07-26T18:42:00Z",
    item_count: 5,
    items: [
      {
        id: "21111111-1111-4111-8111-111111111111",
        raw_name: "Honeycrisp Apples",
        normalized_name: "honeycrisp apples",
        concept_name: "Honeycrisp apples",
        taxonomy_node_key: "food_dining.groceries.produce.fruit.apples_pears",
        theme_slugs: [],
        measured_value: "1.24",
        measured_unit: "kg",
        unit_price_amount: "5.99",
        unit_price_basis_value: "1",
        unit_price_basis_unit: "kg",
        normalized_unit: "kg",
        normalized_unit_price_amount: "5.99",
        line_total_amount: "7.43",
      },
      {
        id: "31111111-1111-4111-8111-111111111111",
        raw_name: "Greek Yogurt",
        normalized_name: "greek yogurt",
        concept_name: "Greek yogurt",
        brand: "Oikos",
        taxonomy_node_key: "food_dining.groceries.dairy_eggs.yogurt_fermented.yogurt",
        theme_slugs: [],
        quantity: "2",
        unit: "each",
        package_value: "650",
        package_unit: "g",
        normalized_unit: "kg",
        normalized_unit_price_amount: "8.45",
        line_total_amount: "10.99",
      },
      {
        id: "41111111-1111-4111-8111-111111111111",
        raw_name: "Sourdough Loaf",
        normalized_name: "sourdough loaf",
        taxonomy_node_key: "food_dining.groceries.bread_bakery.bread",
        theme_slugs: [],
        quantity: "1",
        unit: "each",
        unit_price_amount: "5.49",
        normalized_unit: "each",
        normalized_unit_price_amount: "5.49",
        line_total_amount: "5.49",
      },
      {
        id: "51111111-1111-4111-8111-111111111111",
        raw_name: "Organic Eggs",
        normalized_name: "organic eggs",
        taxonomy_node_key: "food_dining.groceries.dairy_eggs.eggs",
        theme_slugs: [],
        quantity: "1",
        unit: "each",
        package_value: "12",
        package_unit: "each",
        normalized_unit: "each",
        normalized_unit_price_amount: "0.54",
        line_total_amount: "6.49",
      },
      {
        id: "61111111-1111-4111-8111-111111111111",
        raw_name: "Dish Soap",
        normalized_name: "dish soap",
        taxonomy_node_key: "housing_utilities.household_operations.dishwashing_supplies",
        theme_slugs: [],
        quantity: "1",
        unit: "each",
        package_value: "532",
        package_unit: "ml",
        normalized_unit: "L",
        normalized_unit_price_amount: "8.44",
        line_total_amount: "4.49",
      },
    ],
    adjustments: [],
    validation_issues: [],
  },
  receipt: {
    receipt: {
      id: "71111111-1111-4111-8111-111111111111",
      transaction_id: "11111111-1111-4111-8111-111111111111",
    },
    files: [
      {
        id: "81111111-1111-4111-8111-111111111111",
        original_filename: "farm-boy-jul-26.jpg",
        mime_type: "image/jpeg",
        upload_status: "uploaded",
      },
    ],
  },
};

const transactionB: ExpenseSnapshot = {
  transaction: {
    id: "12222222-2222-4222-8222-222222222222",
    status: "draft",
    source_type: "receipt",
    transaction_type: "expense",
    transaction_date: "2026-07-25",
    merchant_name_raw: "Shoppers Drug Mart",
    merchant_name_normalized: "Shoppers Drug Mart",
    currency: "CAD",
    subtotal_amount: "23.17",
    tax_amount: "3.01",
    total_amount: "26.18",
    reconciliation_delta_amount: "0",
    updated_at: "2026-07-25T16:12:00Z",
    item_count: 2,
    items: [
      {
        raw_name: "Face Cleanser",
        normalized_name: "face cleanser",
        taxonomy_node_key: "personal_care.products.skin",
        theme_slugs: [],
        quantity: "1",
        unit: "each",
        package_value: "200",
        package_unit: "ml",
        line_total_amount: "13.99",
      },
      {
        raw_name: "Toothpaste",
        normalized_name: "toothpaste",
        taxonomy_node_key: "personal_care.products.oral",
        theme_slugs: [],
        quantity: "2",
        unit: "each",
        package_value: "100",
        package_unit: "ml",
        line_total_amount: "9.18",
      },
    ],
    adjustments: [],
    validation_issues: [
      {
        severity: "warning",
        code: "category_review",
        message: "Review one low-confidence category.",
      },
    ],
  },
  receipt: null,
};

const moreTransactions = [
  {
    id: "13333333-3333-4333-8333-333333333333",
    status: "confirmed" as const,
    source_type: "manual",
    transaction_type: "expense",
    transaction_date: "2026-07-24",
    merchant_name_normalized: "TTC",
    currency: "CAD",
    total_amount: "25.00",
    item_count: 1,
    items: [],
  },
  {
    id: "14444444-4444-4444-8444-444444444444",
    status: "confirmed" as const,
    source_type: "receipt",
    transaction_type: "expense",
    transaction_date: "2026-07-22",
    merchant_name_normalized: "Pizzeria Libretto",
    currency: "CAD",
    total_amount: "48.60",
    item_count: 3,
    items: [],
  },
  {
    id: "15555555-5555-4555-8555-555555555555",
    status: "confirmed" as const,
    source_type: "email",
    transaction_type: "expense",
    transaction_date: "2026-07-19",
    merchant_name_normalized: "Adobe",
    currency: "USD",
    total_amount: "22.59",
    item_count: 1,
    items: [],
  },
  {
    id: "16666666-6666-4666-8666-666666666666",
    status: "confirmed" as const,
    source_type: "receipt",
    transaction_type: "expense",
    transaction_date: "2026-07-18",
    merchant_name_normalized: "No Frills",
    currency: "CAD",
    total_amount: "84.12",
    item_count: 11,
    items: [],
  },
];

export const demoCategories: Category[] = TAXONOMY_V2.nodes
  .filter((node) => node.is_assignable)
  .map((node) => ({
    id: node.id,
    slug: node.stable_key,
    stable_key: node.stable_key,
    name: node.name,
    is_assignable: node.is_assignable,
    level: node.level,
    level_name: TAXONOMY_V2.levels[node.level - 1],
    path: node.path.map((part) => ({ ...part })),
  }));

const demoDailySpend = (() => {
  const rows: NonNullable<ExpenseDashboard["daily_spend"]> = [];
  const months: Array<[number, number, number]> = [
    [2026, 5, 31],
    [2026, 6, 30],
    [2026, 7, 27],
  ];
  for (const [year, month, lastDay] of months) {
    for (let day = 1; day <= lastDay; day += 1) {
      if ((day * 7 + month) % 3 === 0) continue;
      const amount = (((day * 37 + month * 11) % 88) + 9).toFixed(2);
      rows.push({
        spend_date: `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`,
        currency: "CAD",
        amount,
        transaction_count: 1 + (day % 2),
      });
    }
  }

  // Keep the illustrative calendar totals honest for the handful of days that
  // also have a real (confirmed) transaction in recent_transactions, so a
  // calendar day cell always agrees with what its expanded list shows.
  const realDailyTotals: Array<{ date: string; currency: string; amount: string }> = [
    { date: "2026-07-26", currency: "CAD", amount: "56.28" }, // Farm Boy
    { date: "2026-07-24", currency: "CAD", amount: "25.00" }, // TTC
    { date: "2026-07-22", currency: "CAD", amount: "48.60" }, // Pizzeria Libretto
    { date: "2026-07-19", currency: "USD", amount: "22.59" }, // Adobe
    { date: "2026-07-18", currency: "CAD", amount: "84.12" }, // No Frills
  ];
  for (const real of realDailyTotals) {
    const existing = rows.find(
      (row) => row.spend_date === real.date && row.currency === real.currency,
    );
    if (existing) {
      existing.amount = real.amount;
      existing.transaction_count = 1;
    } else {
      rows.push({
        spend_date: real.date,
        currency: real.currency,
        amount: real.amount,
        transaction_count: 1,
      });
    }
  }
  return rows;
})();

export const demoDashboard: ExpenseDashboard = {
  display_name: "Adi",
  default_currency: "CAD",
  window: {
    label: "July",
    current_start: "2026-07-01",
    current_end: "2026-07-27",
    previous_start: "2026-06-01",
    previous_end: "2026-06-30",
  },
  daily_spend: demoDailySpend,
  totals: [
    {
      currency: "CAD",
      current_amount: "486.32",
      previous_amount: "431.18",
      delta_amount: "55.14",
      delta_percent: "12.8",
    },
    {
      currency: "USD",
      current_amount: "22.59",
      previous_amount: "41.24",
      delta_amount: "-18.65",
      delta_percent: "-45.2",
    },
  ],
  categories: [
    {
      category_slug: "food_dining.groceries",
      category_name: "Groceries",
      taxonomy_level: 2,
      taxonomy_level_name: "Group",
      has_children: true,
      currency: "CAD",
      current_amount: "226.84",
      previous_amount: "198.14",
      delta_percent: "14.5",
      share_percent: "46.6",
    },
    {
      category_slug: "food_dining.eating_out",
      category_name: "Eating out",
      taxonomy_level: 2,
      taxonomy_level_name: "Group",
      has_children: true,
      currency: "CAD",
      current_amount: "91.20",
      previous_amount: "121.30",
      delta_percent: "-24.8",
      share_percent: "18.8",
    },
    {
      category_slug: "shopping_retail.general_merchandise",
      category_name: "General Merchandise",
      taxonomy_level: 2,
      taxonomy_level_name: "Group",
      has_children: true,
      currency: "CAD",
      current_amount: "63.28",
      previous_amount: "38.20",
      delta_percent: "65.7",
      share_percent: "13.0",
    },
    {
      category_slug: "transportation.personal_vehicle",
      category_name: "Personal Vehicle",
      taxonomy_level: 2,
      taxonomy_level_name: "Group",
      has_children: true,
      currency: "CAD",
      current_amount: "55.00",
      previous_amount: "48.54",
      delta_percent: "13.3",
      share_percent: "11.3",
    },
    {
      category_slug: "entertainment_leisure.cinema",
      category_name: "Cinema",
      taxonomy_level: 2,
      taxonomy_level_name: "Group",
      has_children: true,
      currency: "CAD",
      current_amount: "50.00",
      previous_amount: "25.00",
      delta_percent: "100",
      share_percent: "10.3",
    },
  ],
  spend_trend: [
    { period_start: "2026-02-01", label: "Feb", currency: "CAD", amount: "312.40" },
    { period_start: "2026-03-01", label: "Mar", currency: "CAD", amount: "398.18" },
    { period_start: "2026-04-01", label: "Apr", currency: "CAD", amount: "354.92" },
    { period_start: "2026-05-01", label: "May", currency: "CAD", amount: "447.10" },
    { period_start: "2026-06-01", label: "Jun", currency: "CAD", amount: "431.18" },
    { period_start: "2026-07-01", label: "Jul", currency: "CAD", amount: "486.32" },
    { period_start: "2026-06-01", label: "Jun", currency: "USD", amount: "41.24" },
    { period_start: "2026-07-01", label: "Jul", currency: "USD", amount: "22.59" },
  ],
  insights: [
    {
      kind: "review",
      title: "2 expenses need review",
      detail: "Drafts stay out of totals until you confirm them.",
      tone: "attention",
    },
    {
      kind: "price",
      title: "Apples are up 18.1%",
      detail: "CAD $5.99/kg at Farm Boy.",
      tone: "negative",
    },
    {
      kind: "category",
      title: "Eating out is down 24.8%",
      detail: "That is CAD $30.10 less than last month.",
      tone: "positive",
    },
  ],
  recent_transactions: [
    transactionA.transaction,
    transactionB.transaction,
    ...moreTransactions,
  ],
  needs_review_count: 2,
  price_changes: [
    {
      identity_key: "product:apples",
      label: "Apples",
      taxonomy_key: "food_dining.groceries.produce.fruit.apples_pears.apples",
      currency: "CAD",
      normalized_unit: "kg",
      current_price: "5.99",
      previous_price: "5.07",
      delta_amount: "0.92",
      delta_percent: "18.1",
      current_date: "2026-07-26",
      previous_date: "2026-07-09",
      current_merchant: "Farm Boy",
      previous_merchant: "No Frills",
      best_price: "5.07",
      best_date: "2026-07-09",
      best_merchant: "No Frills",
      best_quantity_label: "2.1 lb",
      comparison_price: "5.99",
      comparison_merchant: "Farm Boy",
      savings_amount: "0.92",
      savings_percent: "15.4",
      sample_size: 5,
      recent_prices: ["5.79", "5.29", "5.07", "5.49", "5.99"],
    },
    {
      identity_key: "product:pasta",
      label: "Pasta",
      taxonomy_key: "food_dining.groceries.grains_pasta.pasta",
      currency: "CAD",
      normalized_unit: "kg",
      current_price: "4.75",
      previous_price: "3.99",
      delta_amount: "0.76",
      delta_percent: "19.0",
      current_date: "2026-07-26",
      previous_date: "2026-07-04",
      current_merchant: "Farm Boy",
      previous_merchant: "FreshCo",
      best_price: "3.99",
      best_date: "2026-07-04",
      best_merchant: "FreshCo",
      best_quantity_label: "900 g",
      comparison_price: "4.75",
      comparison_merchant: "Farm Boy",
      savings_amount: "0.76",
      savings_percent: "16.0",
      sample_size: 4,
      recent_prices: ["4.29", "3.99", "4.39", "4.75"],
    },
    {
      identity_key: "product:onions",
      label: "Onions",
      taxonomy_key: "food_dining.groceries.produce.vegetables.alliums.onions",
      currency: "CAD",
      normalized_unit: "kg",
      current_price: "3.67",
      previous_price: null,
      delta_amount: null,
      delta_percent: null,
      current_date: "2026-07-22",
      previous_date: null,
      current_merchant: "FreshCo",
      previous_merchant: null,
      best_price: "3.67",
      best_date: "2026-07-22",
      best_merchant: "FreshCo",
      best_quantity_label: "1 kg",
      recent_prices: ["3.67"],
      comparison_price: null,
      comparison_merchant: null,
      savings_amount: "0",
      savings_percent: "0",
      sample_size: 1,
    },
    {
      identity_key: "product:garlic",
      label: "Garlic",
      taxonomy_key: "food_dining.groceries.produce.vegetables.alliums.garlic",
      currency: "CAD",
      normalized_unit: "each",
      current_price: "1.49",
      previous_price: null,
      delta_amount: null,
      delta_percent: null,
      current_date: "2026-07-24",
      previous_date: null,
      current_merchant: "FreshCo",
      previous_merchant: null,
      best_price: "1.49",
      best_date: "2026-07-24",
      best_merchant: "FreshCo",
      best_quantity_label: "2 each",
      recent_prices: ["1.49"],
      comparison_price: null,
      comparison_merchant: null,
      savings_amount: "0",
      savings_percent: "0",
      sample_size: 1,
    },
    {
      identity_key: "product:toilet-paper",
      label: "Toilet paper",
      taxonomy_key: "housing_utilities.household_operations.paper_disposables",
      currency: "CAD",
      normalized_unit: "each",
      current_price: "0.92",
      previous_price: "0.85",
      delta_amount: "0.07",
      delta_percent: "8.2",
      current_date: "2026-07-18",
      previous_date: "2026-06-12",
      current_merchant: "Costco",
      previous_merchant: "No Frills",
      best_price: "0.85",
      best_date: "2026-06-12",
      best_merchant: "No Frills",
      best_quantity_label: "24 rolls",
      comparison_price: "0.92",
      comparison_merchant: "Costco",
      savings_amount: "0.07",
      savings_percent: "7.6",
      sample_size: 3,
      recent_prices: ["0.88", "0.85", "0.92"],
    },
  ],
  confirmed_only: true,
};

const demoHistory: ItemPriceHistory = {
  identity_key: "product:apples",
  label: "Apples",
  series: [
    {
      currency: "CAD",
      normalized_unit: "kg",
      points: [
        {
          transaction_id: transactionA.transaction.id,
          transaction_item_id: "21111111-1111-4111-8111-111111111111",
          transaction_date: "2026-07-26",
          merchant_name: "Farm Boy",
          display_name: "Honeycrisp apples",
          currency: "CAD",
          normalized_unit: "kg",
          normalized_unit_price_amount: "5.99",
          measured_value: "1.24",
          measured_unit: "kg",
          line_total_amount: "7.43",
        },
        {
          transaction_id: "17777777-7777-4777-8777-777777777777",
          transaction_item_id: "27777777-7777-4777-8777-777777777777",
          transaction_date: "2026-07-09",
          merchant_name: "No Frills",
          display_name: "Honeycrisp apples",
          currency: "CAD",
          normalized_unit: "kg",
          normalized_unit_price_amount: "5.07",
          measured_value: "2.1",
          measured_unit: "lb",
          line_total_amount: "4.83",
        },
        {
          transaction_id: "18888888-8888-4888-8888-888888888888",
          transaction_item_id: "28888888-8888-4888-8888-888888888888",
          transaction_date: "2026-06-18",
          merchant_name: "FreshCo",
          display_name: "Honeycrisp apples",
          currency: "CAD",
          normalized_unit: "kg",
          normalized_unit_price_amount: "5.49",
          measured_value: "0.8",
          measured_unit: "kg",
          line_total_amount: "4.39",
        },
        {
          transaction_id: "19999999-9999-4999-8999-999999999999",
          transaction_item_id: "29999999-9999-4999-8999-999999999999",
          transaction_date: "2026-05-23",
          merchant_name: "Metro",
          display_name: "Honeycrisp apples",
          currency: "CAD",
          normalized_unit: "kg",
          normalized_unit_price_amount: "6.37",
          measured_value: "1.5",
          measured_unit: "lb",
          line_total_amount: "4.33",
        },
      ],
    },
  ],
};

const demoPersonalBasket: PersonalBasketIndex = {
  currency: "CAD",
  window_days: 180,
  overall_delta_percent: "3.8",
  product_count: 3,
  total_tracked_spend: "377.00",
  covered_spend: "298.50",
  coverage_percent: "79.2",
  confidence: "low",
  products: [
    {
      identity_key: "greek-yogurt@kg@store:farm-boy",
      label: "Greek Yogurt",
      merchant_name: "Farm Boy",
      currency: "CAD",
      normalized_unit: "kg",
      baseline_price: "8.00",
      baseline_date: "2026-05-05",
      current_price: "7.00",
      current_date: "2026-07-15",
      delta_percent: "-12.5",
      spend_amount: "150.00",
      purchase_count: 2,
    },
    {
      identity_key: "honeycrisp-apples@kg@store:no-frills",
      label: "No Frills Honeycrisp Apples",
      merchant_name: "No Frills",
      currency: "CAD",
      normalized_unit: "kg",
      baseline_price: "5.00",
      baseline_date: "2026-05-10",
      current_price: "6.00",
      current_date: "2026-07-20",
      delta_percent: "20.0",
      spend_amount: "132.00",
      purchase_count: 2,
    },
    {
      identity_key: "toilet-paper::charmin@each@store:costco",
      label: "Charmin Toilet Paper",
      merchant_name: "Costco",
      currency: "CAD",
      normalized_unit: "each",
      baseline_price: "0.85",
      baseline_date: "2026-05-12",
      current_price: "0.92",
      current_date: "2026-07-18",
      delta_percent: "8.2",
      spend_amount: "16.50",
      purchase_count: 2,
    },
  ],
};

const demoMerchantBreakdown: MerchantBreakdownResponse = {
  window: demoDashboard.window,
  currency: "CAD",
  merchants: [
    {
      merchant_name: "Farm Boy",
      currency: "CAD",
      current_amount: "203.40",
      previous_amount: "181.02",
      delta_percent: "12.4",
      share_percent: "41.8",
      visit_count: 6,
      average_amount: "33.90",
    },
    {
      merchant_name: "No Frills",
      currency: "CAD",
      current_amount: "84.12",
      previous_amount: "88.64",
      delta_percent: "-5.1",
      share_percent: "17.3",
      visit_count: 2,
      average_amount: "42.06",
    },
    {
      merchant_name: "Pizzeria Libretto",
      currency: "CAD",
      current_amount: "48.60",
      previous_amount: "0",
      delta_percent: null,
      share_percent: "10.0",
      visit_count: 1,
      average_amount: "48.60",
    },
    {
      merchant_name: "TTC",
      currency: "CAD",
      current_amount: "25.00",
      previous_amount: "25.00",
      delta_percent: "0",
      share_percent: "5.1",
      visit_count: 1,
      average_amount: "25.00",
    },
  ],
};

const demoNutritionSummary: NutritionSummary = {
  window: demoDashboard.window,
  currency: "CAD",
  overall_grade: "b",
  matched_item_count: 5,
  total_item_count: 7,
  coverage_percent: "71.4",
  confidence: "low",
  grade_distribution: [
    { grade: "a", spend_amount: "18.50", share_percent: "30.0" },
    { grade: "b", spend_amount: "6.00", share_percent: "10.0" },
    { grade: "c", spend_amount: "12.30", share_percent: "20.0" },
    { grade: "e", spend_amount: "12.00", share_percent: "20.0" },
    { grade: "unknown", spend_amount: "12.20", share_percent: "20.0" },
  ],
  signals: [
    {
      kind: "processing_level",
      title: "Mostly whole foods",
      detail: "3 of 5 matched items are minimally processed (NOVA 1-2), led by Fresh Milk 2%, Greek Yogurt.",
      tone: "neutral",
    },
  ],
  groups: [
    {
      category_slug: "food_dining.groceries.dairy_eggs",
      category_name: "Dairy & Eggs",
      items: [
        {
          transaction_item_id: "d1111111-1111-4111-8111-111111111111",
          identity_key: "2-milk::farm-boy",
          display_name: "Fresh Milk 2%",
          brand: "Farm Boy",
          status: "matched",
          purchase_count: 3,
          nutriscore_grade: "a",
          nutriscore_source: "computed",
          nova_group: 1,
          source: "Open Food Facts",
          source_ref: "https://world.openfoodfacts.org/product/example-milk",
          spend_amount: "6.50",
          energy_kcal_100g: 61,
          protein_100g: 3.3,
          fat_100g: 2.0,
          saturated_fat_100g: 1.3,
          trans_fat_100g: 0,
          carbohydrates_100g: 4.8,
          sugars_100g: 4.8,
          fiber_100g: 0,
          sodium_mg_100g: 44,
          cholesterol_mg_100g: 10,
          potassium_mg_100g: 150,
          calcium_mg_100g: 120,
          iron_mg_100g: 0,
        },
        {
          transaction_item_id: "d2222222-2222-4222-8222-222222222222",
          identity_key: "old-cheddar-cheese::no-frills",
          display_name: "Old Cheddar Cheese",
          brand: "No Frills",
          status: "matched",
          purchase_count: 1,
          nutriscore_grade: "d",
          nutriscore_source: "computed",
          nova_group: 3,
          source: "Open Food Facts",
          source_ref: "https://world.openfoodfacts.org/product/example-cheese",
          spend_amount: "12.00",
          energy_kcal_100g: 402,
          protein_100g: 25,
          fat_100g: 33,
          saturated_fat_100g: 21,
          carbohydrates_100g: 1.3,
          sugars_100g: 0.5,
          fiber_100g: 0,
          sodium_mg_100g: 620,
        },
      ],
    },
    {
      category_slug: "food_dining.groceries.snacks_pantry",
      category_name: "Snacks & Pantry",
      items: [
        {
          transaction_item_id: "d3333333-3333-4333-8333-333333333333",
          identity_key: "granola-bars-oats-honey::no-frills",
          display_name: "Granola Bars, Oats & Honey",
          brand: "No Frills",
          status: "matched",
          purchase_count: 1,
          nutriscore_grade: "c",
          nutriscore_source: "computed",
          nova_group: 4,
          nova_group_estimated: true,
          source: "Open Food Facts",
          source_ref: "https://world.openfoodfacts.org/product/example-granola",
          spend_amount: "6.30",
          energy_kcal_100g: 471,
          protein_100g: 7,
          fat_100g: 19,
          saturated_fat_100g: 8,
          carbohydrates_100g: 64,
          sugars_100g: 29,
          added_sugars_100g: 22,
          fiber_100g: 5,
          sodium_mg_100g: 280,
          serving_size_g: 40,
          serving_label: "2 bars (40g)",
        },
        {
          transaction_item_id: "d4444444-4444-4444-8444-444444444444",
          identity_key: "potato-chips-original::no-frills",
          display_name: "Potato Chips, Original",
          brand: "No Frills",
          status: "matched",
          purchase_count: 2,
          nutriscore_grade: "e",
          nutriscore_source: "source_stated",
          nova_group: 4,
          source: "Open Food Facts",
          source_ref: "https://world.openfoodfacts.org/product/example-chips",
          spend_amount: "6.00",
          energy_kcal_100g: 536,
          protein_100g: 6,
          fat_100g: 34,
          saturated_fat_100g: 3.5,
          carbohydrates_100g: 53,
          sugars_100g: 1,
          fiber_100g: 4,
          sodium_mg_100g: 620,
        },
        {
          transaction_item_id: "d5555555-5555-4555-8555-555555555555",
          identity_key: "no-name-trail-mix::no-frills",
          display_name: "No Name Trail Mix",
          brand: "No Frills",
          status: "no_match",
          purchase_count: 1,
          spend_amount: "12.20",
        },
      ],
    },
    {
      category_slug: "food_dining.groceries.frozen",
      category_name: "Frozen",
      items: [
        {
          transaction_item_id: "d6666666-6666-4666-8666-666666666666",
          identity_key: "frozen-peas::freshco",
          display_name: "Frozen Peas",
          brand: "FreshCo",
          status: "matched",
          purchase_count: 1,
          nutriscore_grade: "a",
          nutriscore_source: "computed",
          nova_group: 1,
          source: "Open Food Facts",
          source_ref: "https://world.openfoodfacts.org/product/example-peas",
          spend_amount: "12.00",
          energy_kcal_100g: 78,
          protein_100g: 5.4,
          fat_100g: 0.4,
          saturated_fat_100g: 0.1,
          carbohydrates_100g: 14,
          sugars_100g: 5,
          fiber_100g: 5,
          sodium_mg_100g: 3,
          potassium_mg_100g: 130,
        },
        {
          transaction_item_id: "d7777777-7777-4777-8777-777777777777",
          identity_key: "bananas-bunch::",
          display_name: "Bananas Bunch",
          status: "pending",
          purchase_count: 1,
          spend_amount: "5.00",
        },
      ],
    },
  ],
};

let demoTransactions = new Map<string, ExpenseSnapshot>([
  [transactionA.transaction.id, transactionA],
  [transactionB.transaction.id, transactionB],
]);

function result(structuredContent: Record<string, unknown>, meta?: Record<string, unknown>): ToolResult {
  return { structuredContent, _meta: meta };
}

export async function demoCallTool(
  name: string,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  await new Promise((resolve) => window.setTimeout(resolve, 120));
  if (name === "get_expense_taxonomy") {
    return result({
      assignable_nodes: demoCategories,
      adjustment_types: ["discount", "tax", "fee", "tip", "deposit", "rounding"],
      supported_currencies: ["CAD", "USD"],
      receipt_files: {
        allowed_mime_types: ["image/jpeg", "image/png", "image/webp", "application/pdf"],
        max_file_bytes: 10 * 1024 * 1024,
      },
    });
  }
  if (name === "get_expense_dashboard") {
    const request = (args.request || {}) as { period?: string };
    const labels: Record<string, string> = {
      month: "July",
      "30d": "Last 30 days",
      "90d": "Last 90 days",
      year: "2026",
    };
    return result({
      ...demoDashboard,
      window: {
        ...demoDashboard.window,
        label: labels[request.period || "month"],
      },
      recent_transactions: demoDashboard.recent_transactions.filter(
        (transaction) => !transaction.id.startsWith("deleted:"),
      ),
    });
  }
  if (name === "list_expenses") {
    const filters = (args.filters || {}) as {
      limit?: number;
      offset?: number;
      start_date?: string;
      end_date?: string;
      status?: string;
      currency?: string;
      merchant?: string;
    };
    let all = demoDashboard.recent_transactions.filter(
      (transaction) =>
        !transaction.id.startsWith("deleted:") &&
        (!filters.start_date || transaction.transaction_date >= filters.start_date) &&
        (!filters.end_date || transaction.transaction_date <= filters.end_date) &&
        (!filters.status || transaction.status === filters.status) &&
        (!filters.currency || transaction.currency === filters.currency) &&
        (!filters.merchant ||
          (transaction.merchant_name_normalized || transaction.merchant_name_raw || "")
            .toLowerCase() === filters.merchant.toLowerCase()),
    );
    // The calendar view's daily totals are synthesized independently of the
    // handful of illustrative demo transactions. Backfill a single plausible
    // row so tapping any colored calendar day shows something coherent.
    if (!all.length && filters.start_date && filters.start_date === filters.end_date) {
      const currency = filters.currency || demoDashboard.default_currency;
      const daily = demoDashboard.daily_spend?.find(
        (entry) => entry.spend_date === filters.start_date && entry.currency === currency,
      );
      if (daily && Number(daily.amount) > 0) {
        all = [
          {
            id: `demo-day:${filters.start_date}`,
            status: "confirmed",
            source_type: "manual",
            transaction_type: "expense",
            transaction_date: filters.start_date,
            merchant_name_normalized: "Daily purchases",
            currency,
            total_amount: daily.amount,
            item_count: daily.transaction_count,
          },
        ];
      }
    }
    const limit = filters.limit || 10;
    const offset = filters.offset || 0;
    return result({
      transactions: all.slice(offset, offset + limit),
      total: all.length,
      limit,
      offset,
    });
  }
  if (name === "get_expense_analytics") {
    const query = (args.query || {}) as {
      filters?: { taxonomy_node_key?: string };
      taxonomy_rollup_level?: number;
    };
    const parentKey = query.filters?.taxonomy_node_key;
    const nextLevel = query.taxonomy_rollup_level;
    const children = TAXONOMY_V2.nodes
      .filter(
        (node) =>
          node.parent_key === parentKey &&
          (nextLevel === undefined || node.level === nextLevel),
      )
      .slice(0, 7);
    return result({
      rows: children.map((node, index) => ({
        dimensions: { category: node.stable_key },
        metrics: { total_spend: String(Math.max(12, 108 - index * 15)) },
      })),
      confirmed_only: true,
    });
  }
  if (name === "get_expense") {
    const id = String(args.transaction_id);
    return result(demoTransactions.get(id) || transactionA);
  }
  if (name === "get_item_price_history") {
    const request = args.request as { identity_key?: string } | undefined;
    const requestedKey = request?.identity_key;
    const basketMatch = requestedKey?.startsWith("basket:")
      ? demoPersonalBasket.products.find(
          (product) => `basket:${product.identity_key}` === requestedKey,
        )
      : undefined;
    return result({
      ...demoHistory,
      identity_key: requestedKey || demoHistory.identity_key,
      label:
        basketMatch?.label ||
        requestedKey?.split(":").slice(1).join(":") ||
        demoHistory.label,
    });
  }
  if (name === "get_personal_basket_index") {
    const request = args.request as { currency?: string } | undefined;
    return result({
      ...demoPersonalBasket,
      currency: request?.currency || demoPersonalBasket.currency,
      products: demoPersonalBasket.products.map((product) => ({
        ...product,
        currency: request?.currency || product.currency,
      })),
    });
  }
  if (name === "get_merchant_breakdown") {
    const request = (args.request || {}) as { currency?: string };
    const currency = request.currency || demoMerchantBreakdown.currency;
    return result({
      ...demoMerchantBreakdown,
      currency,
      merchants: demoMerchantBreakdown.merchants.map((merchant) => ({
        ...merchant,
        currency,
      })),
    });
  }
  if (name === "get_nutrition_summary") {
    const request = (args.request || {}) as { currency?: string };
    const currency = request.currency || demoNutritionSummary.currency;
    return result({ ...demoNutritionSummary, currency });
  }
  if (name === "save_expense_draft") {
    const wrapper = args.payload as {
      draft?: Record<string, unknown>;
      transaction_id?: string;
    };
    const draft = wrapper.draft || {};
    const id = wrapper.transaction_id || crypto.randomUUID();
    const snapshot: ExpenseSnapshot = {
      transaction: {
        id,
        status: "draft",
        source_type: String(draft.source_type || "manual"),
        transaction_type: "expense",
        transaction_date: String(draft.transaction_date),
        merchant_name_raw: String(draft.merchant_name_raw || ""),
        merchant_name_normalized: String(draft.merchant_name_normalized || ""),
        notes: draft.notes ? String(draft.notes) : null,
        currency: String(draft.currency || "CAD"),
        subtotal_amount: draft.subtotal_amount as string | undefined,
        tax_amount: draft.tax_amount as string | undefined,
        fee_amount: draft.fee_amount as string | undefined,
        discount_amount: draft.discount_amount as string | undefined,
        tip_amount: draft.tip_amount as string | undefined,
        deposit_amount: draft.deposit_amount as string | undefined,
        rounding_amount: draft.rounding_amount as string | undefined,
        total_amount: String(draft.total_amount || "0"),
        reconciliation_delta_amount: "0",
        updated_at: new Date().toISOString(),
        items: ((draft.items || []) as ExpenseSnapshot["transaction"]["items"]),
        adjustments: [],
        validation_issues: [],
      },
      receipt: draft.receipt
        ? {
            receipt: { id: crypto.randomUUID(), transaction_id: id },
            files: [],
          }
        : null,
    };
    demoTransactions.set(id, snapshot);
    return result({ expense: snapshot, idempotent_replay: false });
  }
  if (name === "validate_expense") {
    return result({
      transaction_id: args.transaction_id,
      reconciliation_delta_amount: "0",
      computed_total_amount: "0",
      issues: [],
      confirmation_eligible: true,
    });
  }
  if (name === "confirm_expense") {
    const id = String(args.transaction_id);
    const snapshot = demoTransactions.get(id) || transactionB;
    const confirmed = {
      ...snapshot,
      transaction: { ...snapshot.transaction, status: "confirmed" as const },
    };
    demoTransactions.set(id, confirmed);
    return result(confirmed);
  }
  if (name === "create_receipt_draft") {
    const payload = args.payload as { transaction_date?: string; currency?: string };
    const id = crypto.randomUUID();
    const snapshot: ExpenseSnapshot = {
      transaction: {
        id,
        status: "draft",
        source_type: "receipt",
        transaction_type: "expense",
        transaction_date: payload.transaction_date || localIsoDate(new Date()),
        currency: payload.currency || "CAD",
        total_amount: "0",
        updated_at: new Date().toISOString(),
        items: [],
      },
      receipt: {
        receipt: { id: crypto.randomUUID(), transaction_id: id },
        files: [],
      },
    };
    demoTransactions.set(id, snapshot);
    return result(snapshot);
  }
  if (name === "delete_expense") {
    demoTransactions.delete(String(args.transaction_id));
    return result({ ok: true, message: "Expense deleted" });
  }
  if (name === "get_receipt_download_url") {
    return result(
      { file_id: args.file_id, expires_at: new Date(Date.now() + 60_000).toISOString() },
      { dailyExpenseTracker: { downloadUrl: "https://example.com/demo-receipt" } },
    );
  }
  if (name === "delete_receipt_file") {
    return result({ ok: true, message: "Receipt file deleted" });
  }
  throw new Error(`${name} is not simulated in preview mode`);
}
