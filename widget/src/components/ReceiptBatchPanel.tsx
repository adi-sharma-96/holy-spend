import { useEffect, useState } from "react";
import { callTool, structured } from "../bridge";

type Attachment = {
  id: string;
  client_attachment_id: string;
  operation_id: string;
  status: string;
  transaction_id?: string | null;
  retry_reason?: string | null;
  unresolved_issues?: Array<{ question?: string; code?: string; message?: string }>;
};

type Batch = {
  id: string;
  client_batch_id: string;
  attachments: Attachment[];
  counts: Record<string, number>;
};

const labels: Record<string, string> = {
  extraction_pending: "Waiting to extract",
  extracting: "Extracting in chat",
  clarification_needed: "Needs your answer",
  draft_saved: "Draft saved; not confirmed",
  confirmed: "Confirmed purchase",
  exact_duplicate: "Already saved",
  possible_duplicate: "Possible matching order; review",
  retryable_failure: "Retry available",
  terminal_failure: "Could not process",
};

export function ReceiptBatchPanel({
  batchId,
  onBatchIdChange,
}: {
  batchId?: string;
  onBatchIdChange: (id: string) => void;
}) {
  const [entry, setEntry] = useState(batchId || "");
  const [batch, setBatch] = useState<Batch>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (batchId) setEntry(batchId);
  }, [batchId]);

  async function load(id: string) {
    if (!id.trim() || busy) return;
    setBusy(true);
    setError(undefined);
    try {
      const result = await callTool("get_receipt_batch", { batch_id: id.trim() });
      const next = structured<Batch>(result);
      setBatch(next);
      onBatchIdChange(next.id);
    } catch {
      setError("Could not load this batch. Check its ID and try again.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (batchId) void load(batchId);
    // Loading is intentionally keyed only by the persisted batch ID.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId]);

  async function prepareRetry(attachment: Attachment) {
    if (!batch) return;
    setBusy(true);
    setError(undefined);
    try {
      const result = await callTool("record_receipt_progress", {
        payload: {
          batch_id: batch.id,
          attachment_id: attachment.id,
          status: "extracting",
        },
      });
      setBatch(structured<Batch>(result));
    } catch {
      setError("Retry could not be prepared. Refresh the batch before trying again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="receipt-batch-panel" aria-label="Receipt batch progress">
      <h3>Receipt batch</h3>
      <form onSubmit={(event) => { event.preventDefault(); void load(entry); }}>
        <label htmlFor="receipt-batch-id">Batch ID</label>
        <input id="receipt-batch-id" value={entry} onChange={(event) => setEntry(event.target.value)} />
        <button type="submit" disabled={busy || !entry.trim()}>Resume</button>
      </form>
      {error && <p role="alert">{error}</p>}
      {batch && (
        <>
          <p>{batch.attachments.length} attachments · {batch.counts.confirmed || 0} confirmed · {batch.counts.draft_saved || 0} drafts</p>
          <ul>
            {batch.attachments.map((attachment) => (
              <li key={attachment.id}>
                <strong>{attachment.client_attachment_id}</strong>
                <span>{labels[attachment.status] || attachment.status}</span>
                {attachment.transaction_id && <small>Purchase {attachment.transaction_id}</small>}
                {attachment.retry_reason && <small>{attachment.retry_reason}</small>}
                {attachment.unresolved_issues?.map((issue, index) => (
                  <small key={index}>{issue.question || issue.message || issue.code}</small>
                ))}
                {attachment.status === "retryable_failure" && (
                  <button type="button" disabled={busy} onClick={() => void prepareRetry(attachment)}>
                    Prepare retry
                  </button>
                )}
                {attachment.status === "extracting" && (
                  <small>Continue processing this attachment in chat with operation {attachment.operation_id}.</small>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
