import { useMemo, useState } from "react";
import { emptyItem, type DraftForm } from "../draft";
import { humanizeToken, money } from "../format";
import { Icon } from "../icons";
import type { Category, ExpenseSnapshot } from "../types";
import { ConfirmSheet } from "./ConfirmSheet";

type Props = {
  form: DraftForm;
  snapshot?: ExpenseSnapshot;
  categories: Category[];
  currencies: string[];
  adjustmentTypes: string[];
  issues: Array<{ severity: string; code: string; message: string }>;
  approved: boolean;
  busy?: string;
  notice?: string;
  successVisible?: boolean;
  onFormChange: (form: DraftForm) => void;
  onApprovedChange: (approved: boolean) => void;
  onBack: () => void;
  onDone?: () => void;
  onNew: () => void;
  onDownload: (fileId: string) => Promise<void>;
  onDeleteFile: (fileId: string) => Promise<void>;
  onSave: () => Promise<ExpenseSnapshot | undefined>;
  onValidate: () => Promise<void>;
  onConfirm: () => Promise<void>;
  onCorrect?: (reason: string) => Promise<boolean>;
  onDiscard?: () => Promise<void>;
};

const unitOptions = ["", "each", "kg", "g", "lb", "oz", "L", "ml"];
const adjustmentSubtypeOptions: Record<string, string[]> = {
  fee: ["bag_fee", "delivery_fee", "service_fee", "other_fee"],
  coupon: ["membership_benefit", "delivery_discount", "offer", "other_discount"],
  discount: ["membership_benefit", "delivery_discount", "offer", "other_discount"],
};

export function ExpenseEditor({
  form,
  snapshot,
  categories,
  currencies,
  adjustmentTypes,
  issues,
  approved,
  busy,
  notice,
  successVisible = false,
  onFormChange,
  onApprovedChange,
  onBack,
  onDone,
  onNew,
  onDownload,
  onDeleteFile,
  onSave,
  onValidate,
  onConfirm,
  onCorrect,
  onDiscard,
}: Props) {
  const [totalsOpen, setTotalsOpen] = useState(false);
  const [fileToDelete, setFileToDelete] = useState<string>();
  const [discardOpen, setDiscardOpen] = useState(false);
  const [correctionMode, setCorrectionMode] = useState(false);
  const [correctionReason, setCorrectionReason] = useState("");
  const confirmedRecord = snapshot?.transaction.status === "confirmed";
  const isConfirmed = confirmedRecord && !correctionMode;
  const assignableCategories = useMemo(
    () => categories.filter((category) => category.is_assignable),
    [categories],
  );
  const groupedCategories = useMemo(() => {
    const groups = new Map<string, Category[]>();
    for (const category of assignableCategories) {
      const root = category.path?.[0]?.name || "Categories";
      groups.set(root, [...(groups.get(root) || []), category]);
    }
    return [...groups.entries()];
  }, [assignableCategories]);
  const receiptFiles = snapshot?.receipt?.files || [];
  const reconciliationDelta = snapshot?.transaction.reconciliation_delta_amount;
  const computedTotal =
    reconciliationDelta === null || reconciliationDelta === undefined
      ? undefined
      : Number(snapshot?.transaction.total_amount || 0) - Number(reconciliationDelta);

  function patchItem(index: number, values: Partial<DraftForm["items"][number]>) {
    const items = [...form.items];
    const current = items[index];
    if (!current) return;
    items[index] = { ...current, ...values };
    onFormChange({ ...form, items });
  }

  function patchAdjustment(
    index: number,
    values: Partial<DraftForm["adjustments"][number]>,
  ) {
    const adjustments = [...form.adjustments];
    const current = adjustments[index];
    if (!current) return;
    adjustments[index] = { ...current, ...values };
    onFormChange({ ...form, adjustments });
  }

  return (
    <main className="expense-editor">
      <header className="editor-header">
        <button className="back-button" onClick={onBack}>
          <Icon name="back" /> Overview
        </button>
        <div className="editor-heading">
          <span className={`status-chip ${confirmedRecord ? "success" : "attention"}`}>
            {confirmedRecord ? (correctionMode ? "Correction" : "Confirmed") : "Draft"}
          </span>
          <h2>{form.transactionId ? (confirmedRecord ? "Expense details" : "Review expense") : "New expense"}</h2>
          <p>
            {confirmedRecord
              ? correctionMode
                ? "Edit the record, explain why, and explicitly approve the audited correction."
                : "This confirmed expense is included in your insights."
              : "Review the extraction, validate the math, then confirm."}
          </p>
        </div>
        <button className="secondary-button compact-button" onClick={onNew}>
          <Icon name="add" size={16} /> New
        </button>
      </header>

      {notice && <div className="editor-notice">{busy || notice}</div>}

      <div className="editor-layout">
        <div className="editor-main">
          <section className="surface receipt-drop">
            <div className="receipt-drop-copy">
              <span className="receipt-drop-icon"><Icon name="scan" size={24} /></span>
              <div>
                <strong>{receiptFiles.length ? "Original receipt stored" : "Receipt scanning happens in chat"}</strong>
                <p>
                  {receiptFiles.length
                    ? "The original can be viewed here while you review this expense."
                    : "Attach an image or PDF directly in this chat, or continue with manual entry."}
                </p>
              </div>
            </div>
            {receiptFiles.length > 0 && (
              <div className="stored-files">
                {receiptFiles.map((file) => (
                  <div key={file.id}>
                    <Icon name="file" />
                    <span>
                      <strong>{file.original_filename}</strong>
                      <small>{file.upload_status}</small>
                    </span>
                    <button onClick={() => void onDownload(file.id)}>View</button>
                    {!confirmedRecord && (
                      <button
                        className="danger-text"
                        onClick={() => setFileToDelete(file.id)}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="surface editor-section">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">EXPENSE</p>
                <h3>Purchase details</h3>
              </div>
              <span>{form.currency} {form.total ? money(form.total, form.currency) : "—"}</span>
            </div>
            <div className="purchase-grid">
              <label className="merchant-field">
                Merchant
                <input
                  value={form.merchant}
                  onChange={(event) => onFormChange({ ...form, merchant: event.target.value })}
                  disabled={isConfirmed}
                  placeholder="Store or vendor"
                />
              </label>
              <label>
                Date
                <input
                  type="date"
                  value={form.date}
                  onChange={(event) => onFormChange({ ...form, date: event.target.value })}
                  disabled={isConfirmed}
                />
              </label>
              <label>
                Currency
                <select
                  value={form.currency}
                  onChange={(event) => onFormChange({ ...form, currency: event.target.value })}
                  disabled={isConfirmed}
                >
                  {currencies.map((currency) => <option key={currency}>{currency}</option>)}
                </select>
              </label>
              <label className="total-field">
                Total
                <input
                  inputMode="decimal"
                  value={form.total}
                  onChange={(event) => onFormChange({ ...form, total: event.target.value })}
                  disabled={isConfirmed}
                  placeholder="0.00"
                />
              </label>
            </div>
            <label className="notes-field">
              Note <span>optional</span>
              <textarea
                value={form.notes}
                onChange={(event) => onFormChange({ ...form, notes: event.target.value })}
                disabled={isConfirmed}
                placeholder="Context you may want later"
              />
            </label>
            <button className="disclosure-button" onClick={() => setTotalsOpen((current) => !current)}>
              <span>Subtotal, tax, discount & other totals</span>
              <Icon name={totalsOpen ? "arrow-up" : "arrow-down"} />
            </button>
            {totalsOpen && (
              <div className="totals-grid">
                {([
                  ["subtotal", "Subtotal"],
                  ["discount", "Discount"],
                  ["tax", "Tax"],
                  ["fee", "Fee"],
                  ["tip", "Tip"],
                  ["deposit", "Deposit"],
                  ["rounding", "Rounding"],
                ] as const).map(([field, label]) => (
                  <label key={field}>
                    {label}
                    <input
                      inputMode="decimal"
                      value={form[field]}
                      onChange={(event) => onFormChange({ ...form, [field]: event.target.value })}
                      disabled={isConfirmed}
                      placeholder="—"
                    />
                  </label>
                ))}
              </div>
            )}
          </section>

          <section className="surface editor-section">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">LINE ITEMS</p>
                <h3>{form.items.length ? `${form.items.length} captured` : "No items yet"}</h3>
              </div>
              {!isConfirmed && (
                <button
                  className="text-button"
                  disabled={!assignableCategories.length}
                  onClick={() =>
                    onFormChange({
                      ...form,
                      items: [
                        ...form.items,
                        emptyItem(assignableCategories[0]?.slug || "miscellaneous"),
                      ],
                    })
                  }
                >
                  <Icon name="add" size={16} /> Add item
                </button>
              )}
            </div>
            <div className="editable-items">
              <div className="editable-item-head">
                <span>Item & category</span>
                <span>Quantity</span>
                <span>Weight / package</span>
                <span>Unit price</span>
                <span>Total</span>
              </div>
              {form.items.map((item, index) => (
                <div className="editable-item" key={`${index}-${item.name}`}>
                  <div className="item-identity-fields">
                    <input
                      aria-label={`Item ${index + 1} name`}
                      value={item.name}
                      onChange={(event) => patchItem(index, { name: event.target.value })}
                      disabled={isConfirmed}
                      placeholder="Item name"
                    />
                    <input
                      aria-label={`Item ${index + 1} brand`}
                      value={item.brand}
                      onChange={(event) => patchItem(index, { brand: event.target.value })}
                      disabled={isConfirmed}
                      placeholder="Brand (optional)"
                    />
                    <select
                      aria-label={`Item ${index + 1} category`}
                      value={item.categorySlug}
                      onChange={(event) => patchItem(index, { categorySlug: event.target.value })}
                      disabled={isConfirmed}
                    >
                      {groupedCategories.map(([root, nodes]) => (
                        <optgroup label={root} key={root}>
                          {nodes.map((category) => (
                            <option value={category.slug} key={category.id}>
                              {category.path?.slice(1).map((part) => part.name).join(" › ")
                                || category.name}
                            </option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                  </div>
                  <div className="paired-input">
                    <input
                      aria-label={`Item ${index + 1} quantity`}
                      inputMode="decimal"
                      value={item.quantity}
                      onChange={(event) => patchItem(index, { quantity: event.target.value })}
                      disabled={isConfirmed}
                      placeholder="1"
                    />
                    <select
                      aria-label={`Item ${index + 1} quantity unit`}
                      value={item.unit}
                      onChange={(event) => patchItem(index, { unit: event.target.value })}
                      disabled={isConfirmed}
                    >
                      {unitOptions.map((unit) => <option key={unit || "blank"}>{unit}</option>)}
                    </select>
                  </div>
                  <div className="measure-fields">
                    <div className="paired-input">
                      <input
                        aria-label={`Item ${index + 1} measured value`}
                        inputMode="decimal"
                        value={item.measuredValue}
                        onChange={(event) => patchItem(index, { measuredValue: event.target.value })}
                        disabled={isConfirmed}
                        placeholder="Weight"
                      />
                      <select
                        aria-label={`Item ${index + 1} measured unit`}
                        value={item.measuredUnit}
                        onChange={(event) => patchItem(index, { measuredUnit: event.target.value })}
                        disabled={isConfirmed}
                      >
                        {unitOptions.filter((unit) => !["each"].includes(unit)).map((unit) => (
                          <option key={unit || "blank"}>{unit}</option>
                        ))}
                      </select>
                    </div>
                    <span>or package</span>
                    <div className="paired-input">
                      <input
                        aria-label={`Item ${index + 1} package value`}
                        inputMode="decimal"
                        value={item.packageValue}
                        onChange={(event) => patchItem(index, { packageValue: event.target.value })}
                        disabled={isConfirmed}
                        placeholder="Size"
                      />
                      <select
                        aria-label={`Item ${index + 1} package unit`}
                        value={item.packageUnit}
                        onChange={(event) => patchItem(index, { packageUnit: event.target.value })}
                        disabled={isConfirmed}
                      >
                        {unitOptions.map((unit) => <option key={unit || "blank"}>{unit}</option>)}
                      </select>
                    </div>
                  </div>
                  <div className="unit-price-fields">
                    <input
                      aria-label={`Item ${index + 1} unit price`}
                      inputMode="decimal"
                      value={item.unitPrice}
                      onChange={(event) => patchItem(index, { unitPrice: event.target.value })}
                      disabled={isConfirmed}
                      placeholder="0.00"
                    />
                    <div className="paired-input basis-input">
                      <input
                        aria-label={`Item ${index + 1} price basis value`}
                        inputMode="decimal"
                        value={item.unitPriceBasisValue}
                        onChange={(event) => patchItem(index, { unitPriceBasisValue: event.target.value })}
                        disabled={isConfirmed}
                        placeholder="per"
                      />
                      <select
                        aria-label={`Item ${index + 1} price basis unit`}
                        value={item.unitPriceBasisUnit}
                        onChange={(event) => patchItem(index, { unitPriceBasisUnit: event.target.value })}
                        disabled={isConfirmed}
                      >
                        {unitOptions.map((unit) => <option key={unit || "blank"}>{unit}</option>)}
                      </select>
                    </div>
                  </div>
                  <input
                    className="line-total-input"
                    aria-label={`Item ${index + 1} total`}
                    inputMode="decimal"
                    value={item.lineTotal}
                    onChange={(event) => patchItem(index, { lineTotal: event.target.value })}
                    disabled={isConfirmed}
                    placeholder="0.00"
                  />
                  {!isConfirmed && (
                    <button
                      className="remove-item"
                      aria-label={`Remove item ${index + 1}`}
                      onClick={() =>
                        onFormChange({
                          ...form,
                          items: form.items.filter((_, itemIndex) => itemIndex !== index),
                        })
                      }
                    >
                      <Icon name="trash" size={15} />
                    </button>
                  )}
                </div>
              ))}
              {!form.items.length && (
                <div className="empty-state compact">
                  <Icon name="receipt" />
                  <span>Add an item manually, or attach a receipt in the chat for extraction.</span>
                </div>
              )}
            </div>
            <p className="data-note inline-note">
              Weight and package size unlock honest kg/lb, L/ml, and per-item price comparisons.
            </p>
          </section>

          <details className="surface adjustments-section" open={form.adjustments.length > 0}>
              <summary>
                <span>
                  <strong>Detailed adjustments</strong>
                  <small>Fees, discounts, benefits, deposits, tips, and tax</small>
                </span>
                <Icon name="chevron" />
              </summary>
              <div className="adjustment-list">
                {form.adjustments.map((adjustment, index) => (
                  <div
                    className={adjustment.affectsTotal ? "" : "informational-adjustment"}
                    key={`${adjustment.type}-${index}`}
                  >
                    <select
                      value={adjustment.type}
                      disabled={isConfirmed}
                      aria-label={`Adjustment ${index + 1} type`}
                      onChange={(event) =>
                        patchAdjustment(index, {
                          type: event.target.value,
                          subtype: "",
                        })
                      }
                    >
                      {adjustmentTypes.map((type) => <option key={type}>{type}</option>)}
                    </select>
                    <select
                      value={adjustment.subtype}
                      disabled={isConfirmed || !(adjustmentSubtypeOptions[adjustment.type]?.length)}
                      aria-label={`Adjustment ${index + 1} subtype`}
                      onChange={(event) => patchAdjustment(index, { subtype: event.target.value })}
                    >
                      <option value="">No subtype</option>
                      {(adjustmentSubtypeOptions[adjustment.type] || []).map((subtype) => (
                        <option value={subtype} key={subtype}>
                          {humanizeToken(subtype)}
                        </option>
                      ))}
                    </select>
                    <input
                      value={adjustment.rawLabel}
                      disabled={isConfirmed}
                      aria-label={`Adjustment ${index + 1} receipt label`}
                      onChange={(event) => patchAdjustment(index, { rawLabel: event.target.value })}
                      placeholder="Exact receipt label"
                    />
                    <input
                      inputMode="decimal"
                      value={adjustment.amount}
                      disabled={isConfirmed}
                      aria-label={`Adjustment ${index + 1} amount`}
                      onChange={(event) => patchAdjustment(index, { amount: event.target.value })}
                      placeholder="0.00"
                    />
                    <label className="affects-total-check">
                      <input
                        type="checkbox"
                        checked={adjustment.affectsTotal}
                        disabled={isConfirmed}
                        onChange={(event) =>
                          patchAdjustment(index, { affectsTotal: event.target.checked })
                        }
                      />
                      {adjustment.affectsTotal ? "Charged" : "Informational"}
                    </label>
                    {!adjustment.affectsTotal && (
                      <small className="informational-note">Excluded from arithmetic</small>
                    )}
                    {!isConfirmed && (
                      <button
                        className="remove-item"
                        aria-label={`Remove adjustment ${index + 1}`}
                        onClick={() =>
                          onFormChange({
                            ...form,
                            adjustments: form.adjustments.filter(
                              (_, adjustmentIndex) => adjustmentIndex !== index,
                            ),
                          })
                        }
                      >
                        <Icon name="trash" size={15} />
                      </button>
                    )}
                  </div>
                ))}
                {!isConfirmed && (
                  <button
                    className="text-button"
                    onClick={() =>
                      onFormChange({
                        ...form,
                        adjustments: [
                          ...form.adjustments,
                          {
                            type: adjustmentTypes[0] || "discount",
                            subtype: "",
                            amount: "",
                            description: "",
                            rawLabel: "",
                            affectsTotal: true,
                            metadata: {},
                          },
                        ],
                      })
                    }
                  >
                    <Icon name="add" size={16} /> Add adjustment
                  </button>
                )}
              </div>
            </details>
        </div>

        <aside className="editor-side">
          <section className="surface review-card">
            <p className="section-kicker">REVIEW & CONFIRM</p>
            <h3>
              {confirmedRecord
                ? correctionMode
                  ? "Correct confirmed expense"
                  : "Expense confirmed"
                : issues.length
                  ? `${issues.length} issue${issues.length === 1 ? "" : "s"}`
                  : "Ready to validate"}
            </h3>
            <p>
              {confirmedRecord
                ? correctionMode
                  ? "The replacement is revision-checked, revalidated, and recorded in the audit trail."
                  : "This record is included in your dashboard and price history."
                : "Validation reconciles the line items and receipt total before confirmation."}
            </p>

            {computedTotal !== undefined && (
              <div className="reconcile-grid">
                <span>
                  Calculated
                  <strong>{money(computedTotal, form.currency)}</strong>
                </span>
                <span>
                  Difference
                  <strong>{money(Number(reconciliationDelta), form.currency)}</strong>
                </span>
              </div>
            )}

            {issues.length > 0 && (
              <div className="issue-list">
                {issues.map((issue) => (
                  <div className={issue.severity} key={`${issue.code}-${issue.message}`}>
                    <span>{issue.severity}</span>
                    <p>{issue.message}</p>
                  </div>
                ))}
              </div>
            )}

            {!confirmedRecord ? (
              <>
                <div className="review-actions">
                  <button className="secondary-button" onClick={() => void onSave()} disabled={Boolean(busy)}>
                    Save draft
                  </button>
                  <button className="primary-button" onClick={() => void onValidate()} disabled={Boolean(busy)}>
                    Validate
                  </button>
                </div>
                <label className="approval-check">
                  <input
                    type="checkbox"
                    checked={approved}
                    onChange={(event) => onApprovedChange(event.target.checked)}
                  />
                  <span>I reviewed the merchant, items, totals, and receipt.</span>
                </label>
                <button
                  className="confirm-button"
                  disabled={
                    !approved ||
                    !snapshot ||
                    issues.some((issue) => issue.severity === "blocking") ||
                    Boolean(busy)
                  }
                  onClick={() => void onConfirm()}
                >
                  Confirm expense
                </button>
                <small className="confirm-note">
                  Confirmation adds this expense to insights and price history.
                </small>
                {snapshot && (
                  <button
                    className="danger-text discard-draft-button"
                    type="button"
                    onClick={() => setDiscardOpen(true)}
                  >
                    Discard draft
                  </button>
                )}
              </>
            ) : correctionMode ? (
              <div className="correction-panel">
                <label>
                  Correction reason
                  <textarea
                    value={correctionReason}
                    onChange={(event) => setCorrectionReason(event.target.value)}
                    placeholder="What was wrong with the confirmed record?"
                    maxLength={500}
                  />
                </label>
                <label className="approval-check">
                  <input
                    type="checkbox"
                    checked={approved}
                    onChange={(event) => onApprovedChange(event.target.checked)}
                  />
                  <span>I reviewed and approve this audited correction.</span>
                </label>
                <button
                  className="confirm-button"
                  disabled={!approved || correctionReason.trim().length < 3 || Boolean(busy)}
                  onClick={() => {
                    if (!onCorrect) return;
                    void onCorrect(correctionReason.trim()).then((applied) => {
                      if (applied) {
                        setCorrectionMode(false);
                        setCorrectionReason("");
                      }
                    });
                  }}
                >
                  Apply correction
                </button>
                <button
                  className="secondary-button"
                  onClick={() => {
                    setCorrectionMode(false);
                    setCorrectionReason("");
                    onApprovedChange(false);
                  }}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <div className="confirmed-panel">
                <span><Icon name="sparkle" /></span>
                <strong>{successVisible ? "Expense confirmed" : "Included in insights"}</strong>
                <p>
                  {successVisible
                    ? "Your expense was saved. Press Done when you’re ready to return to the overview."
                    : "Use the overview to see its category and price impact."}
                </p>
                {successVisible && onDone && (
                  <button className="confirm-button" type="button" onClick={onDone}>
                    Done
                  </button>
                )}
                {onCorrect && (
                  <button
                    className="secondary-button"
                    onClick={() => {
                      setCorrectionMode(true);
                      onApprovedChange(false);
                    }}
                  >
                    Correct expense
                  </button>
                )}
              </div>
            )}
          </section>
        </aside>
      </div>
      {fileToDelete && (
        <ConfirmSheet
          title="Delete receipt file?"
          message="This permanently removes the private original from storage."
          confirmLabel="Delete receipt"
          busy={busy}
          onCancel={() => setFileToDelete(undefined)}
          onConfirm={async () => {
            await onDeleteFile(fileToDelete);
            setFileToDelete(undefined);
          }}
        />
      )}
      {discardOpen && (
        <ConfirmSheet
          title="Discard draft?"
          message="This permanently removes the draft and its owned receipt files."
          confirmLabel="Discard draft"
          busy={busy}
          onCancel={() => setDiscardOpen(false)}
          onConfirm={async () => {
            await onDiscard?.();
            setDiscardOpen(false);
          }}
        />
      )}
    </main>
  );
}
