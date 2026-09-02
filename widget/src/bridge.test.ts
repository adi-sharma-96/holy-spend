import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { HostContext } from "./types";

describe("mobile host bridge", () => {
  const originalParent = window.parent;
  const animationFrames: FrameRequestCallback[] = [];
  const postMessage = vi.fn();
  const requestDisplayMode = vi.fn().mockResolvedValue({ mode: "fullscreen" });
  const fakeParent = { postMessage } as unknown as Window;

  beforeAll(() => {
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: fakeParent,
    });
    window.openai = {
      displayMode: "inline",
      maxHeight: 780,
      requestDisplayMode,
    };
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      animationFrames.push(callback);
      return animationFrames.length;
    });
    vi.spyOn(document.documentElement, "getBoundingClientRect").mockReturnValue({
      height: 412,
    } as DOMRect);
  });

  afterAll(() => {
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: originalParent,
    });
    window.openai = undefined;
    vi.restoreAllMocks();
  });

  function flushAnimationFrames() {
    while (animationFrames.length) {
      const callbacks = animationFrames.splice(0);
      callbacks.forEach((callback) => callback(performance.now()));
    }
  }

  it("sizes inline content, declares fullscreen, and stops resizing after expansion", async () => {
    const bridge = await import("./bridge");
    const initialize = postMessage.mock.calls
      .map(([message]) => message as Record<string, unknown>)
      .find((message) => message.method === "ui/initialize");

    expect(initialize).toMatchObject({
      params: {
        appCapabilities: {
          availableDisplayModes: ["inline", "fullscreen"],
        },
      },
    });

    window.dispatchEvent(
      new MessageEvent("message", {
        source: fakeParent,
        data: {
          jsonrpc: "2.0",
          id: initialize?.id,
          result: {
            hostContext: {
              displayMode: "inline",
              platform: "mobile",
              containerDimensions: { maxHeight: 780 },
            },
          },
        },
      }),
    );
    await Promise.resolve();
    flushAnimationFrames();

    expect(
      postMessage.mock.calls.some(
        ([message]) =>
          message.method === "ui/notifications/size-changed" &&
          message.params.height === 412,
      ),
    ).toBe(true);

    await bridge.requestFullscreen();
    expect(requestDisplayMode).toHaveBeenCalledWith({ mode: "fullscreen" });

    postMessage.mockClear();
    window.dispatchEvent(
      new MessageEvent("message", {
        source: fakeParent,
        data: {
          jsonrpc: "2.0",
          method: "ui/notifications/host-context-changed",
          params: { displayMode: "fullscreen" },
        },
      }),
    );
    flushAnimationFrames();

    expect(
      postMessage.mock.calls.some(
        ([message]) => message.method === "ui/notifications/size-changed",
      ),
    ).toBe(false);
  });
});

// window.openai is a ChatGPT-specific synchronous bootstrap optimization, not
// a requirement - any spec-compliant MCP Apps host (Claude, Goose, VS Code)
// talks over the standard postMessage/JSON-RPC channel alone. This suite
// proves the whole flow works with window.openai entirely absent, so a
// future change can't silently reintroduce a hard dependency on it.
describe("standards-only host bridge (no window.openai)", () => {
  const originalParent = window.parent;
  const postMessage = vi.fn();
  const fakeParent = { postMessage } as unknown as Window;

  beforeAll(() => {
    window.openai = undefined;
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: fakeParent,
    });
  });

  afterAll(() => {
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: originalParent,
    });
    vi.restoreAllMocks();
  });

  function findRequest(method: string) {
    return postMessage.mock.calls
      .map(([message]) => message as Record<string, unknown>)
      .find((message) => message.method === method);
  }

  function respond(id: unknown, result: unknown) {
    window.dispatchEvent(
      new MessageEvent("message", {
        source: fakeParent,
        data: { jsonrpc: "2.0", id, result },
      }),
    );
  }

  // Each bridge call chains multiple internal awaits (connection, then the
  // request itself) before it actually posts a message, so a single
  // microtask tick isn't always enough for the postMessage to land.
  async function flush() {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  }

  it("initializes, calls tools, and requests fullscreen purely over standard JSON-RPC", async () => {
    vi.resetModules();
    const bridge = await import("./bridge");

    const initialize = findRequest("ui/initialize");
    expect(initialize).toBeTruthy();
    respond(initialize?.id, {
      hostContext: { displayMode: "inline", theme: "dark", locale: "en-CA" },
    });
    await flush();

    const callPromise = bridge.callTool("get_expense_dashboard", { request: {} });
    await flush();
    const toolsCall = findRequest("tools/call");
    expect(toolsCall).toMatchObject({
      params: { name: "get_expense_dashboard", arguments: { request: {} } },
    });
    respond(toolsCall?.id, { structuredContent: { ok: true } });
    await expect(callPromise).resolves.toEqual({ structuredContent: { ok: true } });

    const fullscreenPromise = bridge.requestFullscreen();
    await flush();
    const displayModeRequest = findRequest("ui/request-display-mode");
    expect(displayModeRequest).toMatchObject({ params: { mode: "fullscreen" } });
    respond(displayModeRequest?.id, {});
    await expect(fullscreenPromise).resolves.toBeUndefined();

    const linkPromise = bridge.openPrivateUrl("https://example.com/receipt.pdf");
    await flush();
    const openLinkRequest = findRequest("ui/open-link");
    expect(openLinkRequest).toMatchObject({ params: { url: "https://example.com/receipt.pdf" } });
    respond(openLinkRequest?.id, {});
    await expect(linkPromise).resolves.toBeUndefined();

    let receivedContext: HostContext | undefined;
    bridge.subscribeToHostContext((context) => {
      receivedContext = context;
    });
    expect(receivedContext).toMatchObject({ displayMode: "inline", theme: "dark" });
  });
});
