type Props = {
  title: string;
  message: string;
  confirmLabel: string;
  busy?: string;
  onCancel: () => void;
  onConfirm: () => Promise<void> | void;
};

export function ConfirmSheet({
  title,
  message,
  confirmLabel,
  busy,
  onCancel,
  onConfirm,
}: Props) {
  return (
    <div className="confirm-backdrop" role="presentation">
      <section className="confirm-sheet" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <h2 id="confirm-title">{title}</h2>
        <p>{message}</p>
        <div className="sheet-actions">
          <button className="secondary-button" type="button" onClick={onCancel} disabled={Boolean(busy)}>
            Cancel
          </button>
          <button className="danger-button" type="button" onClick={() => void onConfirm()} disabled={Boolean(busy)}>
            {busy || confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
