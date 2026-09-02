import { useState } from "react";
import { Icon } from "../icons";
import type { NutritionItem } from "../types";

const NOVA_NOTES: Record<number, string> = {
  1: "NOVA 1, unprocessed or minimally processed. Little to nothing added.",
  2: "NOVA 2, processed culinary ingredient. Used to prepare other foods, not usually eaten alone.",
  3: "NOVA 3, processed food. Made mostly from culinary ingredients with an added preservative or two, not from scratch.",
  4: "NOVA 4, ultra-processed. Industrial formulation with ingredients you wouldn't find in a home kitchen.",
};

function isLikelyUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

export function displayNumber(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function scaled(value: number | null | undefined, factor: number): number | null | undefined {
  return value == null ? value : value * factor;
}

export function NutritionFactsDrawer({
  item,
  onClose,
  embedded = false,
}: {
  item: NutritionItem;
  onClose: () => void;
  embedded?: boolean;
}) {
  const [mode, setMode] = useState<"100g" | "serving">("100g");

  const hasServing = item.serving_size_g != null && item.serving_label != null;
  const factor = mode === "serving" && hasServing ? Number(item.serving_size_g) / 100 : 1;
  const perLabel =
    mode === "serving" && hasServing ? `per ${item.serving_label ?? `${item.serving_size_g}g`}` : "per 100g";

  const grade = item.nutriscore_grade?.toLowerCase();
  const kcal = displayNumber(scaled(item.energy_kcal_100g, factor));
  const protein = displayNumber(scaled(item.protein_100g, factor));
  const carbs = displayNumber(scaled(item.carbohydrates_100g, factor));
  const fat = displayNumber(scaled(item.fat_100g, factor));
  const facts: Array<[string, string | null, string]> = [
    ["Saturated fat", displayNumber(scaled(item.saturated_fat_100g, factor)), "g"],
    ["Trans fat", displayNumber(scaled(item.trans_fat_100g, factor)), "g"],
    ["Cholesterol", displayNumber(scaled(item.cholesterol_mg_100g, factor)), "mg"],
    ["Sugars", displayNumber(scaled(item.sugars_100g, factor)), "g"],
    ["Added sugars", displayNumber(scaled(item.added_sugars_100g, factor)), "g"],
    ["Fibre", displayNumber(scaled(item.fiber_100g, factor)), "g"],
    ["Sodium", displayNumber(scaled(item.sodium_mg_100g, factor)), "mg"],
    ["Potassium", displayNumber(scaled(item.potassium_mg_100g, factor)), "mg"],
    ["Calcium", displayNumber(scaled(item.calcium_mg_100g, factor)), "mg"],
    ["Iron", displayNumber(scaled(item.iron_mg_100g, factor)), "mg"],
  ];
  const novaNote = item.nova_group ? NOVA_NOTES[item.nova_group] : undefined;
  const sourceLink = item.source_ref && isLikelyUrl(item.source_ref) ? item.source_ref : undefined;

  const content = (
    <>
      <header className="drawer-header">
        <button
          className="icon-button"
          onClick={onClose}
          aria-label={embedded ? "Back to Nutrition" : "Close nutrition facts"}
        >
          <Icon name={embedded ? "back" : "close"} />
        </button>
        <div className="drawer-title">
          <div>
            <h2>{item.display_name}</h2>
            <p>
              {item.brand ? `${item.brand} · ` : ""}
              {perLabel}
              {item.source ? `, as reported by ${item.source}` : ""}
            </p>
          </div>
        </div>
        {grade && (
          <div className={`drawer-grade grade-${grade}`}>
            {grade.toUpperCase()}
            {item.nutriscore_source === "source_stated" && <small className="grade-provenance">as reported</small>}
          </div>
        )}
      </header>

      {hasServing && (
        <div className="nutrition-view-bar">
          <div className="view-toggle" role="group" aria-label="Nutrition facts display">
            <button className={mode === "100g" ? "active" : ""} onClick={() => setMode("100g")} type="button">
              100g
            </button>
            <button className={mode === "serving" ? "active" : ""} onClick={() => setMode("serving")} type="button">
              Serving
            </button>
          </div>
        </div>
      )}

      <div className="headline-stats">
        <span>
          Calories
          <strong>{kcal ?? "—"}</strong>
        </span>
        <span>
          Protein
          <strong>
            {protein ?? "—"}
            {protein && <small>g</small>}
          </strong>
        </span>
        <span>
          Carbs
          <strong>
            {carbs ?? "—"}
            {carbs && <small>g</small>}
          </strong>
        </span>
        <span>
          Fat
          <strong>
            {fat ?? "—"}
            {fat && <small>g</small>}
          </strong>
        </span>
      </div>

      <div className="facts-heading">
        <h3>Nutrition facts</h3>
        <span>{perLabel}</span>
      </div>
      <div className="facts-table">
        {facts.map(([label, value, unit]) => (
          <div className="facts-row" key={label}>
            <span>{label}</span>
            <b>
              {value ?? "—"}
              {value && <small> {unit}</small>}
            </b>
          </div>
        ))}
      </div>

      {novaNote && (
        <div className={item.nova_group_estimated ? "nova-note nova-note-estimated" : "nova-note"}>
          <Icon name="sparkle" />
          <span>
            {novaNote}
            {item.nova_group_estimated ? " (estimated from ingredients)" : ""}
          </span>
        </div>
      )}

      {sourceLink && (
        <a className="off-link" href={sourceLink} target="_blank" rel="noreferrer">
          View on {item.source}
          <Icon name="expand" size={11} />
        </a>
      )}
    </>
  );

  if (embedded) {
    return (
      <section className="nutrition-facts-embedded" aria-label={`${item.display_name} nutrition facts`}>
        {content}
      </section>
    );
  }

  return (
    <div
      className="drawer-backdrop"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <aside className="price-drawer" aria-label={`${item.display_name} nutrition facts`}>
        {content}
      </aside>
    </div>
  );
}
