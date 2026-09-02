import { TAXONOMY_V2 } from "./taxonomy.generated";

type GeneratedTaxonomyNode = (typeof TAXONOMY_V2.nodes)[number];

const nodesByKey = new Map<string, GeneratedTaxonomyNode>(
  TAXONOMY_V2.nodes.map((node) => [node.stable_key, node]),
);
const childCountByKey = new Map<string, number>();

for (const node of TAXONOMY_V2.nodes) {
  if (!node.parent_key) continue;
  childCountByKey.set(node.parent_key, (childCountByKey.get(node.parent_key) || 0) + 1);
}

export function taxonomyNode(stableKey: string) {
  return nodesByKey.get(stableKey);
}

export function taxonomyHasChildren(stableKey: string): boolean {
  return (childCountByKey.get(stableKey) || 0) > 0;
}

export function taxonomyLevelName(level: number): string {
  return TAXONOMY_V2.levels[level - 1] || `Level ${level}`;
}

/** Fixed taxonomy depth Deals groups are collapsed at — Subcategory, e.g.
 * "Fruit", "Vegetables", "Milk", "Cheese", "Pulses & Legumes" — broad enough
 * that every variety of a food type lands in one bucket, without going so far
 * up (Group/Category) that unrelated food types get blended together. */
const GROUP_LEVEL = 4;

/** Display name of the ancestor at the fixed grouping level for a leaf, e.g.
 * "Vegetables" for the "broccoli" leaf (whose immediate parent is the
 * narrower "Cruciferous Vegetables" Class) — used to group Deals products
 * by a broad, recognizable category rather than a precariously-named one.
 * Branches shallower than the grouping level (e.g. household/personal-care,
 * which bottom out around level 3) fall back to the item's immediate
 * parent so every item still lands in some named group. */
export function taxonomyGroupLabel(stableKey: string): string | undefined {
  const node = nodesByKey.get(stableKey);
  if (!node) return undefined;
  const subcategory = node.path.find((entry) => entry.level === GROUP_LEVEL);
  if (subcategory) return subcategory.name;
  if (node.parent_key) return nodesByKey.get(node.parent_key)?.name;
  return node.name;
}
