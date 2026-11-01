import { useCallback, useEffect, useRef, useState } from "react";
import { callTool, structured } from "../bridge";

type ReviewRow = {
  id: string;
  transaction_id: string;
  raw_name: string | null;
  normalized_name: string | null;
  brand: string | null;
  taxonomy_key: string | null;
  product_identity_key: string | null;
  product_type_key: string | null;
  field_provenance: Record<string, { source?: string; source_ref?: string; source_text?: string }>;
  evidence_revision: number;
  quantity: string | null;
  unit: string | null;
  measured_value: string | null;
  measured_unit: string | null;
  package_value: string | null;
  package_unit: string | null;
  reasons: string[];
  repeat_count: number;
  line_total_amount: string;
  priority: number;
  last_corrected_at?: string;
  review_decision?: "confirmed" | "rejected" | "deferred" | null;
};

type Preview = {
  operation_id: string;
  affected_count: number;
  affected: Array<{
    item_id: string;
    revision: number;
    before: Record<string, unknown>;
    after: Record<string, unknown>;
  }>;
};

type CorrectionEvent = {
  id: string;
  reason: string;
  created_at: string;
  reversed: boolean;
  reverses_event_id: string | null;
  before_value: Record<string, unknown>;
  after_value: Record<string, unknown>;
};

type ConfirmField = "identity" | "product_type" | "brand" | "quantity" | "package_size" |
  "package_count" | "measured_value";
const CONFIRM_FIELDS: Array<{ key: ConfirmField; label: string }> = [
  { key: "identity", label: "Product identity" },
  { key: "product_type", label: "Product type" },
  { key: "brand", label: "Brand" },
  { key: "quantity", label: "Quantity" },
  { key: "package_size", label: "Package size" },
  { key: "package_count", label: "Package count" },
  { key: "measured_value", label: "Measured amount" },
];

function message(error: unknown): string {
  return error instanceof Error ? error.message : "Review action failed";
}

export function ProductReviewPanel({ onBack }: { onBack: () => void }) {
  const [queue, setQueue] = useState<ReviewRow[]>([]);
  const [recent, setRecent] = useState<ReviewRow[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [selectedRow, setSelectedRow] = useState<ReviewRow>();
  const [showSuppressed, setShowSuppressed] = useState(false);
  const [history, setHistory] = useState<CorrectionEvent[]>([]);
  const [scope, setScope] = useState<"item" | "confirmed_identity">("item");
  const [identity, setIdentity] = useState("");
  const [productType, setProductType] = useState("");
  const [brand, setBrand] = useState("");
  const [taxonomy, setTaxonomy] = useState("");
  const [quantity, setQuantity] = useState("");
  const [unit, setUnit] = useState("");
  const [measuredValue, setMeasuredValue] = useState("");
  const [measuredUnit, setMeasuredUnit] = useState("");
  const [packageValue, setPackageValue] = useState("");
  const [packageUnit, setPackageUnit] = useState("");
  const [reason, setReason] = useState("");
  const [confirmedFields, setConfirmedFields] = useState<ConfirmField[]>([]);
  const [preview, setPreview] = useState<Preview>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const operation = useRef<{ key: string; id: string } | undefined>(undefined);
  const selected = queue.find((row) => row.id === selectedId)
    || recent.find((row) => row.id === selectedId) || selectedRow;
  const selectedIsQueued = queue.some((row) => row.id === selectedId);

  const refresh = useCallback(async () => {
    const [queueResult, recentResult] = await Promise.all([
      callTool("get_product_review_queue", { limit: 100, include_suppressed: showSuppressed }),
      callTool("list_product_corrections", { limit: 50 }),
    ]);
    const rows = structured<ReviewRow[]>(queueResult);
    const recentRows = structured<ReviewRow[]>(recentResult);
    setQueue(rows);
    setRecent(recentRows);
    setSelectedRow((current) => rows.find((row) => row.id === current?.id)
      || recentRows.find((row) => row.id === current?.id) || current);
  }, [showSuppressed]);

  useEffect(() => {
    void refresh().catch((failure: unknown) => setError(message(failure)));
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) return;
    void callTool("get_product_correction_history", { item_id: selectedId })
      .then((result) => setHistory(structured<CorrectionEvent[]>(result)))
      .catch((failure: unknown) => setError(message(failure)));
  }, [selectedId]);

  function choose(row: ReviewRow) {
    setSelectedId(row.id);
    setSelectedRow(row);
    setIdentity(row.product_identity_key || "");
    setProductType(row.product_type_key || "");
    setBrand(row.brand || "");
    setTaxonomy(row.taxonomy_key || "");
    setQuantity(row.quantity || "");
    setUnit(row.unit || "");
    setMeasuredValue(row.measured_value || "");
    setMeasuredUnit(row.measured_unit || "");
    setPackageValue(row.package_value || "");
    setPackageUnit(row.package_unit || "");
    setScope("item");
    setConfirmedFields([]);
    setPreview(undefined);
    setError(undefined);
    setNotice(undefined);
  }

  function patch(): Record<string, unknown> {
    const value: Record<string, unknown> = {};
    if (selected && identity.trim() !== (selected.product_identity_key || "")) {
      value.product_identity_key = identity.trim() || null;
    }
    if (selected && productType.trim() !== (selected.product_type_key || "")) {
      value.product_type_key = productType.trim() || null;
    }
    if (selected && brand.trim() !== (selected.brand || "")) {
      value.brand = brand.trim() || null;
    }
    if (selected && taxonomy.trim() !== (selected.taxonomy_key || "")) {
      value.taxonomy_node_key = taxonomy.trim();
    }
    if (selected && (packageValue !== (selected.package_value || "") || packageUnit !== (selected.package_unit || ""))) {
      value.package_value = packageValue ? Number(packageValue) : null;
      value.package_unit = packageUnit || null;
    }
    if (selected && (quantity !== (selected.quantity || "") || unit !== (selected.unit || ""))) {
      value.quantity = quantity ? Number(quantity) : null;
      value.unit = unit || null;
    }
    if (selected && (measuredValue !== (selected.measured_value || "") || measuredUnit !== (selected.measured_unit || ""))) {
      value.measured_value = measuredValue ? Number(measuredValue) : null;
      value.measured_unit = measuredUnit || null;
    }
    if (confirmedFields.length) value.confirm_fields = confirmedFields;
    return value;
  }

  async function previewCorrection() {
    if (!selected) return;
    setBusy(true);
    setError(undefined);
    try {
      const result = await callTool("preview_product_correction", {
        request: { item_id: selected.id, scope, patch: patch() },
      });
      setPreview(structured<Preview>(result));
    } catch (failure) {
      setError(message(failure));
      setPreview(undefined);
    } finally {
      setBusy(false);
    }
  }

  function operationId(key: string): string {
    if (operation.current?.key === key) return operation.current.id;
    const id = crypto.randomUUID();
    operation.current = { key, id };
    return id;
  }

  async function decide(decision: "confirmed" | "rejected" | "deferred") {
    if (!selected) return;
    if (decision === "confirmed" && !preview) {
      setError("Preview the correction before confirming.");
      return;
    }
    if (reason.trim().length < 3) {
      setError("Add a reason of at least three characters.");
      return;
    }
    const expected = Object.fromEntries(
      decision === "confirmed"
        ? (preview?.affected || []).map((row) => [row.item_id, row.revision])
        : [[selected.id, selected.evidence_revision]],
    );
    const request = {
      item_id: selected.id,
      scope: decision === "confirmed" ? scope : "item",
      patch: decision === "confirmed" ? patch() : {},
      decision,
      reason: reason.trim(),
      expected_revisions: expected,
    };
    setBusy(true);
    setError(undefined);
    try {
      await callTool("decide_product_review", {
        request: { ...request, operation_id: decision === "confirmed" && preview
          ? preview.operation_id : operationId(JSON.stringify(request)) },
      });
      setNotice(`${decision === "confirmed" ? "Corrected" : decision === "rejected" ? "Rejected" : "Deferred"} ${Object.keys(expected).length} item(s).`);
      setPreview(undefined);
      await refresh();
      const result = await callTool("get_product_correction_history", { item_id: selected.id });
      setHistory(structured<CorrectionEvent[]>(result));
    } catch (failure) {
      setError(`${message(failure)} Reload the queue and preview again if the item changed.`);
    } finally {
      setBusy(false);
    }
  }

  async function reverse(event: CorrectionEvent) {
    if (!selected || reason.trim().length < 3) {
      setError("Add a reason before reversing.");
      return;
    }
    const request = { event_id: event.id, reason: reason.trim() };
    setBusy(true);
    setError(undefined);
    try {
      await callTool("reverse_product_correction", {
        request: { ...request, operation_id: operationId(`reverse:${JSON.stringify(request)}`) },
      });
      setNotice("Correction reversed.");
      await refresh();
      const result = await callTool("get_product_correction_history", { item_id: selected.id });
      setHistory(structured<CorrectionEvent[]>(result));
    } catch (failure) {
      setError(`${message(failure)} A later edit may require a new review.`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="overview product-review" aria-label="Fix my matches">
      <div className="panel-heading">
        <div><h2>Fix my matches</h2><p>Review source evidence before changing product data.</p></div>
        <button type="button" className="secondary-button" onClick={onBack}>Back to overview</button>
      </div>
      {error && <p role="alert" className="app-error">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="overview-grid">
        <section className="surface">
          <h3>Needs review ({queue.length})</h3>
          <label><input type="checkbox" checked={showSuppressed}
            onChange={(event) => setShowSuppressed(event.target.checked)} /> Show deferred and rejected</label>
          {queue.length === 0 && <p>No product evidence issues in this page.</p>}
          {queue.map((row) => (
            <button key={row.id} type="button" className="review-row" onClick={() => choose(row)}
              aria-pressed={selectedId === row.id}>
              <strong>{row.normalized_name || row.raw_name || "Unnamed item"}</strong>
              <span>{row.reasons.join(", ")}</span>
              {row.review_decision && <small>Last decision: {row.review_decision}</small>}
              <small>{row.repeat_count} similar lines · {row.line_total_amount} · priority {row.priority.toFixed(0)}</small>
            </button>
          ))}
          <h3>Recent corrections ({recent.length})</h3>
          {recent.length === 0 && <p>No product corrections yet.</p>}
          {recent.map((row) => <button key={row.id} type="button" className="review-row"
            onClick={() => choose(row)} aria-label={`View correction history for ${row.normalized_name || row.raw_name}`}>
            <strong>{row.normalized_name || row.raw_name || "Unnamed item"}</strong>
            {row.last_corrected_at && <small>Corrected {row.last_corrected_at}</small>}
          </button>)}
        </section>
        <section className="surface">
          {!selected ? <p>Select an item to inspect its evidence and correction history.</p> : <>
            <h3>{selected.normalized_name || selected.raw_name}</h3>
            {!selectedIsQueued && <p>This item has left the review queue. Its correction history remains available.</p>}
            <p>Receipt text: {selected.raw_name || "Unavailable"}</p>
            <p>Reporting leaf: {selected.taxonomy_key || "Unknown"}</p>
            <p>Evidence: {JSON.stringify(selected.field_provenance)}</p>
            <p>Reasons: {selected.reasons.join(", ")}</p>
            <label>Product identity <input value={identity} onChange={(event) => { setIdentity(event.target.value); setPreview(undefined); }} /></label>
            <label>Product type <input value={productType} onChange={(event) => { setProductType(event.target.value); setPreview(undefined); }} /></label>
            <label>Brand <input value={brand} onChange={(event) => { setBrand(event.target.value); setPreview(undefined); }} /></label>
            <label>Taxonomy leaf <input value={taxonomy} onChange={(event) => { setTaxonomy(event.target.value); setPreview(undefined); }} /></label>
            <label>Quantity <input type="number" min="0.001" step="any" value={quantity}
              onChange={(event) => { setQuantity(event.target.value); setPreview(undefined); }} /></label>
            <label>Quantity unit <input value={unit} onChange={(event) => { setUnit(event.target.value); setPreview(undefined); }} /></label>
            <label>Measured amount <input type="number" min="0.001" step="any" value={measuredValue}
              onChange={(event) => { setMeasuredValue(event.target.value); setPreview(undefined); }} /></label>
            <label>Measured unit <input value={measuredUnit}
              onChange={(event) => { setMeasuredUnit(event.target.value); setPreview(undefined); }} /></label>
            <label>Package size <input type="number" min="0.001" step="any" value={packageValue}
              onChange={(event) => { setPackageValue(event.target.value); setPreview(undefined); }} /></label>
            <label>Package unit <input value={packageUnit}
              onChange={(event) => { setPackageUnit(event.target.value); setPreview(undefined); }} /></label>
            <fieldset><legend>Confirm existing values after checking their source</legend>
              {CONFIRM_FIELDS.map(({ key, label }) => <label key={key}>
                <input type="checkbox" checked={confirmedFields.includes(key)}
                  onChange={(event) => {
                    setConfirmedFields(event.target.checked
                      ? [...confirmedFields, key]
                      : confirmedFields.filter((field) => field !== key));
                    setPreview(undefined);
                  }} /> {label}
              </label>)}
            </fieldset>
            <label>Scope <select value={scope} onChange={(event) => { setScope(event.target.value as typeof scope); setPreview(undefined); }}>
              <option value="item">This item only</option>
              <option value="confirmed_identity">Identical confirmed records</option>
            </select></label>
            <label>Decision reason <input value={reason} onChange={(event) => setReason(event.target.value)} /></label>
            <div className="panel-actions">
              <button type="button" disabled={busy} onClick={() => void previewCorrection()}>Preview correction</button>
              <button type="button" disabled={busy || !preview} onClick={() => void decide("confirmed")}>Confirm</button>
              <button type="button" disabled={busy} onClick={() => void decide("rejected")}>Reject</button>
              <button type="button" disabled={busy} onClick={() => void decide("deferred")}>Defer</button>
            </div>
            {preview && <div role="region" aria-label="Correction preview">
              <h4>Preview: {preview.affected_count} record(s)</h4>
              {preview.affected.map((row) => <pre key={row.item_id}>{JSON.stringify({
                item_id: row.item_id, revision: row.revision, before: row.before, after: row.after,
              }, null, 2)}</pre>)}
            </div>}
            <h4>Correction history</h4>
            {history.length === 0 && <p>No corrections yet.</p>}
            {history.map((event) => <div key={event.id}>
              <p>{event.created_at}: {event.reason}{event.reversed ? " (reversed)" : ""}</p>
              {!event.reversed && !event.reverses_event_id &&
                <button type="button" disabled={busy} onClick={() => void reverse(event)}>Reverse</button>}
            </div>)}
          </>}
        </section>
      </div>
    </main>
  );
}
