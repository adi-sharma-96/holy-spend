import { useRef } from "react";
import { Icon } from "../icons";

type Props = {
  busy?: string;
  onClose: () => void;
  onReceipt: (file: File) => Promise<void>;
  onManual: () => Promise<void>;
};

export function AddExpenseSheet({
  busy,
  onClose,
  onReceipt,
  onManual,
}: Props) {
  const uploadRef = useRef<HTMLInputElement>(null);

  return (
    <div
      className="sheet-backdrop compact-choice-backdrop"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <section className="add-sheet compact-choice-sheet" aria-label="Add expense">
        <header>
          <div>
            <p className="section-kicker">ADD EXPENSE</p>
            <h2>Choose a starting point</h2>
            <p>Nothing is saved until a populated draft is ready.</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close add expense">
            <Icon name="close" />
          </button>
        </header>

        <div className="capture-grid two-choice-grid">
          <button
            className="capture-card primary-capture"
            onClick={() => uploadRef.current?.click()}
            disabled={Boolean(busy)}
          >
            <span><Icon name="camera" size={25} /></span>
            <strong>Scan/upload receipt</strong>
            <small>JPEG, PNG, WebP, or PDF</small>
          </button>
          <button
            className="capture-card"
            onClick={() => void onManual()}
            disabled={Boolean(busy)}
          >
            <span><Icon name="add" size={25} /></span>
            <strong>Enter manually</strong>
            <small>Open a blank review form</small>
          </button>
        </div>
        <input
          className="visually-hidden"
          ref={uploadRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,application/pdf"
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (file) void onReceipt(file);
            event.currentTarget.value = "";
          }}
        />

        <p className="privacy-note">
          <Icon name="scan" size={15} />
          Receipt originals are stored privately only after extraction creates a meaningful draft.
        </p>
      </section>
    </div>
  );
}
