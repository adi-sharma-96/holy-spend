import { useState } from "react";
import {
  fullDate,
  humanizeToken,
  identityKey,
  itemName,
  money,
  quantityLabel,
  unitPriceLabel,
} from "../format";
import { Icon } from "../icons";
import type { ExpenseSnapshot, ItemPriceHistory } from "../types";
import { ConfirmSheet } from "./ConfirmSheet";

type Props = {
  snapshot: ExpenseSnapshot;
  busy?: string;
  onClose: () => void;
  onEdit: () => void;
  onDelete: () => Promise<void>;
  onDownload: (fileId: string) => Promise<void>;
  onPriceHistory: (identityKey: string, currency: string) => Promise<ItemPriceHistory | undefined>;
};

export function TransactionDetail({
  snapshot,
  busy,
  onClose,
  onEdit,
  onDelete,
  onDownload,
  onPriceHistory,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const transaction = snapshot.transaction;
  const items = Array.isArray(transaction.items) ? transaction.items : [];
  const adjustments = Array.isArray(transaction.adjustments)
    ? transaction.adjustments
    : [];
  const receiptFiles = Array.isArray(snapshot.receipt?.files)
    ? snapshot.receipt.files
    : [];
  const merchant =
    transaction.merchant_name_normalized ||
    transaction.merchant_name_raw ||
    "Manual expense";

  return (
    <div
      className="drawer-backdrop"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <aside className="detail-drawer" aria-label="Transaction details">
        <header className="drawer-header">
          <button className="icon-button" onClick={onClose} aria-label="Close transaction details">
            <Icon name="close" />
          </button>
          <div className="drawer-title">
            <span className={`transaction-mark ${transaction.status}`}>
              <Icon name="receipt" />
            </span>
            <div>
              <h2>{merchant}</h2>
              <p>
                {fullDate(transaction.transaction_date)} ·{" "}
                {humanizeToken(transaction.source_type, "manual expense")}
              </p>
            </div>
          </div>
          <div className="more-wrap">
            <button
              className="icon-button"
              onClick={() => setMenuOpen((current) => !current)}
              aria-label="More actions"
            >
              <Icon name="more" />
            </button>
            {menuOpen && (
              <div className="context-menu">
                <button
                  className="danger"
                  onClick={() => {
                    setMenuOpen(false);
                    setConfirmDelete(true);
                  }}
                >
                  <Icon name="trash" size={16} /> Delete expense
                </button>
              </div>
            )}
          </div>
        </header>

        <div className="detail-total">
          <span>{transaction.status === "draft" ? "Draft total" : "Total"}</span>
          <strong>{money(transaction.total_amount, transaction.currency)}</strong>
          <span className={`status-chip ${transaction.status === "draft" ? "attention" : "success"}`}>
            {transaction.status === "draft" ? "Needs review" : "Confirmed"}
          </span>
        </div>

        <section className="detail-section">
          <div className="panel-heading">
            <h3>Line items</h3>
            <span>
              {items.length} item{items.length === 1 ? "" : "s"}
            </span>
          </div>
          <div className="line-item-table">
            <div className="line-item-head">
              <span>Item</span>
              <span>Qty / size</span>
              <span>Unit price</span>
              <span>Total</span>
            </div>
            {items.map((item, index) => {
              const key = identityKey(item);
              const taxonomyPath = Array.isArray(item.taxonomy_path)
                ? item.taxonomy_path
                    .map((part) => part?.name)
                    .filter((name): name is string => typeof name === "string" && Boolean(name))
                    .join(" › ")
                : "";
              const categoryParts =
                typeof item.category_slug === "string"
                  ? item.category_slug.split(".")
                  : [];
              const categoryLeaf = categoryParts[categoryParts.length - 1];
              return (
                <div className="line-item-view" key={item.id || `${itemName(item)}-${index}`}>
                  <span className="line-item-name">
                    <strong>{itemName(item)}</strong>
                    <small>
                      {taxonomyPath
                        || item.taxonomy_node_name
                        || humanizeToken(categoryLeaf, "")
                        || "Needs review"}
                    </small>
                  </span>
                  <span>{quantityLabel(item)}</span>
                  <span>
                    {unitPriceLabel(item, transaction.currency)}
                    {key && (
                      <button
                        className="micro-link"
                        disabled={Boolean(busy)}
                        onClick={() => void onPriceHistory(key, transaction.currency)}
                      >
                        View price watch
                      </button>
                    )}
                  </span>
                  <strong>{money(item.line_total_amount, transaction.currency)}</strong>
                </div>
              );
            })}
            {!items.length && (
              <p className="empty-copy detail-empty">No item-level details were captured.</p>
            )}
          </div>
        </section>

        <section className="detail-section totals-list">
          <div className="panel-heading">
            <h3>Payment summary</h3>
            <span>{transaction.currency}</span>
          </div>
          {[
            ["Subtotal", transaction.subtotal_amount],
            ["Discount", transaction.discount_amount ? -Number(transaction.discount_amount) : null],
            ["Tax", transaction.tax_amount],
            ["Fee", transaction.fee_amount],
            ["Tip", transaction.tip_amount],
            ["Deposit", transaction.deposit_amount],
            ["Rounding", transaction.rounding_amount],
          ]
            .filter(([, value]) => value !== null && value !== undefined)
            .map(([label, value]) => (
              <div key={String(label)}>
                <span>{label}</span>
                <strong>{money(value as string | number, transaction.currency)}</strong>
              </div>
            ))}
          <div className="grand-total">
            <span>Total</span>
            <strong>{money(transaction.total_amount, transaction.currency)}</strong>
          </div>
        </section>

        {adjustments.length ? (
          <section className="detail-section">
            <div className="panel-heading">
              <h3>Detailed adjustments</h3>
              <span>{adjustments.length} components</span>
            </div>
            <div className="adjustment-detail-list">
              {adjustments.map((adjustment, index) => {
                const label =
                  adjustment.raw_label ||
                  adjustment.description ||
                  humanizeToken(adjustment.subtype, "") ||
                  humanizeToken(adjustment.type);
                const amount =
                  adjustment.affects_total &&
                  ["coupon", "discount"].includes(adjustment.type)
                    ? -Number(adjustment.amount)
                    : adjustment.amount;
                return (
                  <div
                    className={adjustment.affects_total ? "" : "informational-adjustment"}
                    key={adjustment.id || `${adjustment.type}-${index}`}
                  >
                    <span>
                      <strong>{label}</strong>
                      <small>
                        {humanizeToken(
                          adjustment.subtype,
                          humanizeToken(adjustment.type),
                        )}
                        {!adjustment.affects_total ? " · informational saving" : ""}
                      </small>
                    </span>
                    <strong>{money(amount, transaction.currency)}</strong>
                  </div>
                );
              })}
            </div>
          </section>
        ) : null}

        {receiptFiles.length ? (
          <section className="detail-section">
            <div className="panel-heading">
              <h3>Receipt</h3>
              <span>Private storage</span>
            </div>
            <div className="receipt-files">
              {receiptFiles.map((file) => (
                <button key={file.id} onClick={() => void onDownload(file.id)}>
                  <Icon name="file" />
                  <span>
                    <strong>{file.original_filename}</strong>
                    <small>{file.upload_status}</small>
                  </span>
                  <Icon name="chevron" size={16} />
                </button>
              ))}
            </div>
          </section>
        ) : null}

        {transaction.notes && (
          <section className="detail-section note-card">
            <p className="section-kicker">NOTE</p>
            <p>{transaction.notes}</p>
          </section>
        )}

        <footer className="drawer-footer">
          <button className="secondary-button" onClick={onClose}>
            Close
          </button>
          <button className="primary-button" onClick={onEdit}>
            {transaction.status === "draft" ? "Review draft" : "View full details"}
          </button>
        </footer>
        {confirmDelete && (
          <ConfirmSheet
            title={transaction.status === "draft" ? "Discard draft?" : "Delete expense?"}
            message="This permanently removes the expense, its line items, adjustments, receipt metadata, and owned receipt files."
            confirmLabel={transaction.status === "draft" ? "Discard draft" : "Delete expense"}
            busy={busy}
            onCancel={() => setConfirmDelete(false)}
            onConfirm={async () => {
              await onDelete();
              setConfirmDelete(false);
            }}
          />
        )}
      </aside>
    </div>
  );
}
