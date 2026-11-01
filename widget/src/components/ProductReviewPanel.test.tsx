import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { callTool } from "../bridge";
import { ProductReviewPanel } from "./ProductReviewPanel";

vi.mock("../bridge", () => ({
  callTool: vi.fn(),
  structured: (result: { structuredContent: { result: unknown } }) => result.structuredContent.result,
}));

const itemId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const row = {
  id: itemId,
  transaction_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  raw_name: "HONEYCRISP APPLE",
  normalized_name: "Honeycrisp apples",
  brand: null,
  taxonomy_key: "food_dining.groceries.produce.fruit.apples_pears.apples",
  product_identity_key: null,
  product_type_key: null,
  field_provenance: {},
  evidence_revision: 1,
  quantity: "1",
  package_value: null,
  package_unit: null,
  reasons: ["unresolved_identity", "unverified_quantity"],
  repeat_count: 2,
  line_total_amount: "3.50",
  priority: 21,
};

function result(value: unknown) {
  return { structuredContent: { result: value } };
}

describe("ProductReviewPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(callTool).mockImplementation(async (name) => {
      if (name === "get_product_review_queue") return result([row]);
      if (name === "list_product_corrections") return result([]);
      if (name === "get_product_correction_history") return result([]);
      if (name === "preview_product_correction") return result({
        operation_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        affected_count: 1,
        affected: [{ item_id: itemId, revision: 1, before: { product_identity_key: null },
          after: { product_identity_key: "honeycrisp" } }],
      });
      if (name === "decide_product_review") return result({ decision: "confirmed" });
      throw new Error(`Unexpected tool: ${name}`);
    });
  });

  it("shows evidence, previews scope and sends revision-bound confirmation", async () => {
    render(<ProductReviewPanel onBack={vi.fn()} />);
    fireEvent.click(await screen.findByText("Honeycrisp apples"));
    expect(screen.getByText("Receipt text: HONEYCRISP APPLE")).toBeInTheDocument();
    expect(screen.getAllByText(/unresolved_identity, unverified_quantity/)).toHaveLength(2);
    fireEvent.change(screen.getByRole("textbox", { name: "Product identity" }), { target: { value: "honeycrisp" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Product type" }), { target: { value: "apple.honeycrisp" } });
    fireEvent.change(screen.getByLabelText("Decision reason"), { target: { value: "Checked label" } });
    fireEvent.click(screen.getByText("Preview correction"));
    expect(await screen.findByText("Preview: 1 record(s)")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Confirm"));
    await waitFor(() => expect(callTool).toHaveBeenCalledWith("decide_product_review", {
      request: expect.objectContaining({
        item_id: itemId,
        decision: "confirmed",
        expected_revisions: { [itemId]: 1 },
        patch: { product_identity_key: "honeycrisp", product_type_key: "apple.honeycrisp" },
      }),
    }));
  });

  it("keeps a stale preview error visible for a new review", async () => {
    vi.mocked(callTool).mockImplementation(async (name) => {
      if (name === "get_product_review_queue") return result([row]);
      if (name === "list_product_corrections") return result([]);
      if (name === "get_product_correction_history") return result([]);
      if (name === "preview_product_correction") throw new Error("Review preview is stale");
      throw new Error(`Unexpected tool: ${name}`);
    });
    render(<ProductReviewPanel onBack={vi.fn()} />);
    fireEvent.click(await screen.findByText("Honeycrisp apples"));
    fireEvent.click(screen.getByText("Preview correction"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Review preview is stale");
    expect(screen.getByText("Confirm")).toBeDisabled();
  });

  it("keeps a resolved item's history and reversal available after it leaves the queue", async () => {
    let resolved = false;
    let reversed = false;
    vi.mocked(callTool).mockImplementation(async (name) => {
      if (name === "get_product_review_queue") return result(resolved && !reversed ? [] : [row]);
      if (name === "list_product_corrections") return result(resolved ? [{ ...row,
        last_corrected_at: "2026-11-01T00:00:00Z" }] : []);
      if (name === "get_product_correction_history") return result(resolved ? [{
        id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        reason: "Checked label", created_at: "2026-11-01T00:00:00Z",
        reversed, reverses_event_id: null,
        before_value: {}, after_value: {},
      }] : []);
      if (name === "preview_product_correction") return result({
        operation_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        affected_count: 1,
        affected: [{ item_id: itemId, revision: 1, before: {}, after: {} }],
      });
      if (name === "decide_product_review") { resolved = true; return result({ decision: "confirmed" }); }
      if (name === "reverse_product_correction") { reversed = true; return result({ decision: "reversed" }); }
      throw new Error(`Unexpected tool: ${name}`);
    });
    const firstScreen = render(<ProductReviewPanel onBack={vi.fn()} />);
    fireEvent.click(await screen.findByText("Honeycrisp apples"));
    fireEvent.change(screen.getByRole("textbox", { name: "Product identity" }), { target: { value: "honeycrisp" } });
    fireEvent.change(screen.getByLabelText("Decision reason"), { target: { value: "Checked label" } });
    fireEvent.click(screen.getByText("Preview correction"));
    await screen.findByText("Preview: 1 record(s)");
    fireEvent.click(screen.getByText("Confirm"));
    expect(await screen.findByText("This item has left the review queue. Its correction history remains available."))
      .toBeInTheDocument();
    firstScreen.unmount();
    render(<ProductReviewPanel onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "View correction history for Honeycrisp apples" }));
    fireEvent.change(screen.getByLabelText("Decision reason"), { target: { value: "Undo correction" } });
    fireEvent.click(await screen.findByText("Reverse"));
    await waitFor(() => expect(callTool).toHaveBeenCalledWith("reverse_product_correction", {
      request: expect.objectContaining({ event_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd" }),
    }));
    expect(await screen.findByText("Correction reversed.")).toBeInTheDocument();
  });

  it("can display a deferred item for an explicit new review", async () => {
    vi.mocked(callTool).mockImplementation(async (name, args) => {
      if (name === "get_product_review_queue") return result(
        (args as { include_suppressed?: boolean }).include_suppressed
          ? [{ ...row, review_decision: "deferred" }] : []
      );
      if (name === "list_product_corrections") return result([]);
      if (name === "get_product_correction_history") return result([]);
      throw new Error(`Unexpected tool: ${name}`);
    });
    render(<ProductReviewPanel onBack={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Show deferred and rejected"));
    expect(await screen.findByText("Last decision: deferred")).toBeInTheDocument();
  });
});
