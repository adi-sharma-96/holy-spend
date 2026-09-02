import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { emptyDraft } from "../draft";
import { ExpenseEditor } from "./ExpenseEditor";

describe("ExpenseEditor adjustments", () => {
  it("renders informational savings, excludes them from arithmetic, and preserves hidden metadata", () => {
    const onFormChange = vi.fn();
    const form = {
      ...emptyDraft(new Date("2026-07-27T12:00:00Z")),
      total: "10.00",
      adjustments: [
        {
          type: "discount",
          subtype: "membership_benefit",
          amount: "3.99",
          description: "Membership saving",
          rawLabel: "Uber One benefit",
          affectsTotal: false,
          metadata: { program: "uber_one" },
        },
      ],
    };

    render(
      <ExpenseEditor
        form={form}
        categories={[]}
        currencies={["CAD"]}
        adjustmentTypes={["discount", "fee", "tax", "tip", "deposit", "rounding"]}
        issues={[]}
        approved={false}
        onFormChange={onFormChange}
        onApprovedChange={vi.fn()}
        onBack={vi.fn()}
        onNew={vi.fn()}
        onDownload={vi.fn()}
        onDeleteFile={vi.fn()}
        onSave={vi.fn()}
        onValidate={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Adjustment 1 subtype")).toHaveValue(
      "membership_benefit",
    );
    expect(screen.getByDisplayValue("Uber One benefit")).toBeInTheDocument();
    expect(screen.getByDisplayValue("3.99")).toBeInTheDocument();
    expect(screen.getByText("Excluded from arithmetic")).toBeInTheDocument();
    expect(screen.getByText("Informational")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Adjustment 1 receipt label"), {
      target: { value: "Updated benefit label" },
    });

    const updated = onFormChange.mock.calls[0]![0];
    expect(updated.adjustments[0]).toMatchObject({
      rawLabel: "Updated benefit label",
      subtype: "membership_benefit",
      affectsTotal: false,
      metadata: { program: "uber_one" },
    });
  });

  it("keeps confirmed success visible until Done is pressed", () => {
    const onDone = vi.fn();
    render(
      <ExpenseEditor
        form={{
          ...emptyDraft(new Date("2026-07-27T12:00:00Z")),
          transactionId: "11111111-1111-4111-8111-111111111111",
          total: "10.00",
        }}
        snapshot={{
          transaction: {
            id: "11111111-1111-4111-8111-111111111111",
            status: "confirmed",
            source_type: "manual",
            transaction_type: "expense",
            transaction_date: "2026-07-27",
            currency: "CAD",
            total_amount: "10.00",
            items: [],
            adjustments: [],
          },
        }}
        categories={[]}
        currencies={["CAD"]}
        adjustmentTypes={[]}
        issues={[]}
        approved={false}
        successVisible
        onFormChange={vi.fn()}
        onApprovedChange={vi.fn()}
        onBack={vi.fn()}
        onDone={onDone}
        onNew={vi.fn()}
        onDownload={vi.fn()}
        onDeleteFile={vi.fn()}
        onSave={vi.fn()}
        onValidate={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getAllByText("Expense confirmed")).toHaveLength(2);
    expect(screen.getByText(/Press Done/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onDone).toHaveBeenCalledOnce();
  });
});
