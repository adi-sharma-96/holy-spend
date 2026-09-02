import { describe, expect, it } from "vitest";
import app from "./App.tsx?raw";
import bridge from "./bridge.ts?raw";
import editor from "./components/ExpenseEditor.tsx?raw";
import overview from "./components/Overview.tsx?raw";
import detail from "./components/TransactionDetail.tsx?raw";

describe("mobile and confirmation UI contracts", () => {
  const components = `${editor}\n${overview}\n${detail}`;

  it("uses explicit in-app confirmations rather than window.confirm", () => {
    expect(`${app}\n${components}`).not.toContain("window.confirm");
    expect(components).toContain("<ConfirmSheet");
  });

  it("contains no UI receipt upload, model follow-up, staging, or polling workflow", () => {
    const source = `${app}\n${bridge}\n${editor}`;
    expect(source).not.toContain('type="file"');
    expect(source).not.toContain("uploadFile");
    expect(source).not.toContain("sendFollowUpMessage");
    expect(source).not.toContain("prepare_receipt_file");
    expect(source).not.toContain("get_receipt_attempt_status");
    expect(source).not.toContain("Reading receipt with ChatGPT");
  });

  it("uses widget-state routes without mutating the host iframe URL", () => {
    expect(app).toContain('"/overview"');
    expect(app).toContain('"/transactions"');
    expect(app).toContain('"/trends"');
    expect(app).toContain('"/prices"');
    expect(app).toContain('"/expenses/new"');
    expect(app).toContain("(\\/review)?");
    expect(app).toContain("persistWidgetState");
    expect(app).not.toContain("window.history.pushState");
    expect(app).not.toContain('window.addEventListener("popstate"');
    expect(app).toContain('document.addEventListener("visibilitychange"');
    expect(app).toContain("window.setInterval");
  });

  it("opens transaction details in the proven in-place drawer", () => {
    expect(app).toContain("setSelectedExpense(next)");
    expect(detail).toContain('className="drawer-backdrop"');
    expect(detail).toContain('className="detail-drawer"');
  });

  it("uses a non-animated document page for transaction details on phones", () => {
    expect(app).toContain("transaction-detail-page-mode");
    expect(app).toContain('hostContext.platform === "mobile"');
  });
});
