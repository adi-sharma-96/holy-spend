import { afterEach, describe, expect, it, vi } from "vitest";
import { measureIntrinsicSize } from "./intrinsic-size";

describe("measureIntrinsicSize", () => {
  afterEach(() => {
    document.documentElement.style.height = "";
    vi.restoreAllMocks();
  });

  it("measures natural content height and restores the host-constrained height", () => {
    document.documentElement.style.height = "0px";
    vi.spyOn(document.documentElement, "getBoundingClientRect").mockImplementation(() => {
      expect(document.documentElement.style.height).toBe("max-content");
      return { height: 638.2 } as DOMRect;
    });

    expect(measureIntrinsicSize()).toMatchObject({ height: 639 });
    expect(document.documentElement.style.height).toBe("0px");
  });

  it("never reports a zero-height widget", () => {
    vi.spyOn(document.documentElement, "getBoundingClientRect").mockReturnValue({
      height: 0,
    } as DOMRect);

    expect(measureIntrinsicSize().height).toBeGreaterThan(0);
  });
});
