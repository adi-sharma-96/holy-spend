import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { callTool } from "../bridge";
import { ReceiptBatchPanel } from "./ReceiptBatchPanel";

vi.mock("../bridge", () => ({
  callTool: vi.fn(),
  structured: (result: { structuredContent: { result: unknown } }) => result.structuredContent.result,
}));

const batch = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  client_batch_id: "batch:twenty",
  counts: { confirmed: 1, draft_saved: 1, retryable_failure: 1, clarification_needed: 1 },
  attachments: [
    { id: "b1", client_attachment_id: "attachment:01", operation_id: "operation:01",
      status: "confirmed", transaction_id: "purchase-1" },
    { id: "b2", client_attachment_id: "attachment:02", operation_id: "operation:02",
      status: "draft_saved", transaction_id: "purchase-2" },
    { id: "b3", client_attachment_id: "attachment:03", operation_id: "operation:03",
      status: "clarification_needed", unresolved_issues: [{ question: "Which packet did you keep?" }] },
    { id: "b4", client_attachment_id: "attachment:04", operation_id: "operation:04",
      status: "retryable_failure", retry_reason: "download_failed" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(callTool).mockImplementation(async (name) => {
    if (name === "get_receipt_batch") return { structuredContent: { result: batch } };
    if (name === "record_receipt_progress") return {
      structuredContent: { result: {
        ...batch,
        counts: { ...batch.counts, retryable_failure: 0, extracting: 1 },
        attachments: batch.attachments.map((row) => row.id === "b4"
          ? { ...row, status: "extracting" } : row),
      } },
    };
    throw new Error(`Unexpected tool: ${name}`);
  });
});

it("reopens persisted batch results and never calls a saved draft confirmed", async () => {
  render(<ReceiptBatchPanel batchId={batch.id} onBatchIdChange={vi.fn()} />);
  expect(await screen.findByText("Draft saved; not confirmed")).toBeInTheDocument();
  expect(screen.getByText("Confirmed purchase")).toBeInTheDocument();
  expect(screen.getByText("Which packet did you keep?")).toBeInTheDocument();
  expect(screen.getByText("download_failed")).toBeInTheDocument();
  fireEvent.click(screen.getByText("Prepare retry"));
  await waitFor(() => expect(callTool).toHaveBeenCalledWith("record_receipt_progress", {
    payload: { batch_id: batch.id, attachment_id: "b4", status: "extracting" },
  }));
  expect(await screen.findByText(/Continue processing this attachment in chat/)).toBeInTheDocument();
});
