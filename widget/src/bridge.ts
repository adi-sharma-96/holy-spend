import { demoCallTool } from "./demo";
import { measureIntrinsicSize } from "./intrinsic-size";
import type { HostContext, ToolResult } from "./types";

// This bridge talks to the host over the standard MCP Apps postMessage/
// JSON-RPC channel (io.modelcontextprotocol/ui) as its one and only
// canonical path - that's what every function below actually runs on,
// and it's what makes this widget work in any spec-compliant host
// (ChatGPT, Claude, Goose, VS Code), not just the one it was first built
// against. `window.openai` only shows up in a few places, and only ever
// as one of:
//   1. A synchronous bootstrap fast-path - ChatGPT injects window.openai
//      before this script runs, so reading it avoids waiting on the
//      async ui/initialize round-trip for the very first paint. Once the
//      real handshake resolves, host context and results flow through
//      the standard channel exactly the same either way.
//   2. Two ChatGPT-only conveniences with no standard equivalent today
//      (persistWidgetState, and reading the initial route off
//      toolInput in App.tsx) - both degrade to a harmless no-op/default
//      on any host that doesn't expose window.openai.
// Any new host-facing call added here should follow the same rule: the
// standard request()/notify() path is the real implementation, and
// window.openai (if used at all) is strictly an optional shortcut with
// a working fallback - never a hard dependency.

type JsonRpcId = number;
type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timeout: number;
};

const listeners = new Set<(result: ToolResult) => void>();
const hostContextListeners = new Set<(context: HostContext) => void>();
const pendingRequests = new Map<JsonRpcId, PendingRequest>();
let nextRequestId = 1;
let latestToolResult: ToolResult | undefined;
let latestHostContext: HostContext | undefined;
let resizeFrame: number | undefined;
let previousWidth = 0;
let previousHeight = 0;

export const isDemoMode =
  typeof window !== "undefined" && new URLSearchParams(window.location.search).has("demo");

function postMessage(message: Record<string, unknown>): void {
  window.parent.postMessage(message, "*");
}

function notify(method: string, params: Record<string, unknown> = {}): void {
  postMessage({ jsonrpc: "2.0", method, params });
}

function request<T>(method: string, params: Record<string, unknown>): Promise<T> {
  const id = nextRequestId++;
  postMessage({ jsonrpc: "2.0", id, method, params });
  return new Promise<T>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      pendingRequests.delete(id);
      reject(new Error(`${method} timed out`));
    }, 60_000);
    pendingRequests.set(id, {
      resolve: resolve as (value: unknown) => void,
      reject,
      timeout,
    });
  });
}

function publishToolResult(result: ToolResult): void {
  latestToolResult = result;
  for (const listener of listeners) listener(result);
}

function publishHostContext(context: HostContext): void {
  latestHostContext = { ...latestHostContext, ...context };
  for (const listener of hostContextListeners) listener(latestHostContext);
  reportIntrinsicSize();
}

function hostContextFromOpenAI(): HostContext | undefined {
  const openai = window.openai;
  if (!openai) return undefined;
  return {
    theme: openai.theme,
    locale: openai.locale,
    displayMode: openai.displayMode,
    containerDimensions:
      typeof openai.maxHeight === "number" ? { maxHeight: openai.maxHeight } : undefined,
    userAgent: openai.userAgent,
    safeAreaInsets: openai.safeArea,
  };
}

function toolResultFromOpenAI(): ToolResult | undefined {
  const openai = window.openai;
  if (!openai?.toolOutput) return undefined;
  return {
    structuredContent: openai.toolOutput,
    _meta: openai.toolResponseMetadata,
  };
}

function handleHostMessage(event: MessageEvent): void {
  if (event.source !== window.parent) return;
  const message = event.data as {
    jsonrpc?: string;
    id?: JsonRpcId;
    result?: unknown;
    error?: { message?: string };
    method?: string;
    params?: unknown;
  };
  if (!message || message.jsonrpc !== "2.0") return;

  if (message.id !== undefined) {
    const pending = pendingRequests.get(message.id);
    if (!pending) return;
    pendingRequests.delete(message.id);
    window.clearTimeout(pending.timeout);
    if (message.error) {
      pending.reject(new Error(message.error.message || "Host request failed"));
    } else {
      pending.resolve(message.result);
    }
    return;
  }

  if (message.method === "ui/notifications/tool-result" && message.params) {
    publishToolResult(message.params as ToolResult);
  } else if (
    message.method === "ui/notifications/host-context-changed" &&
    message.params
  ) {
    publishHostContext(message.params as HostContext);
  }
}

function reportIntrinsicSize(): void {
  if (resizeFrame !== undefined) return;
  resizeFrame = window.requestAnimationFrame(() => {
    resizeFrame = undefined;
    const displayMode = latestHostContext?.displayMode || window.openai?.displayMode;
    if (displayMode !== "inline") return;

    // Match the official MCP Apps bridge: measure the document at its natural
    // content height instead of the iframe height currently imposed by the
    // host. Measuring the constrained frame can report zero on mobile and
    // permanently collapse the widget.
    const { width, height } = measureIntrinsicSize();
    if (width === previousWidth && height === previousHeight) return;
    previousWidth = width;
    previousHeight = height;
    notify("ui/notifications/size-changed", { width, height });
  });
}

function setupAutoResize(): void {
  reportIntrinsicSize();

  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(reportIntrinsicSize);
    observer.observe(document.documentElement);
    if (document.body) observer.observe(document.body);
  }

  window.addEventListener("resize", reportIntrinsicSize, { passive: true });
  window.addEventListener("orientationchange", reportIntrinsicSize, { passive: true });
  window.addEventListener("pageshow", reportIntrinsicSize, { passive: true });
  void document.fonts?.ready.then(reportIntrinsicSize);
}

async function initializeBridge(): Promise<void> {
  window.addEventListener("message", handleHostMessage, { passive: true });
  setupAutoResize();

  const fallbackContext = hostContextFromOpenAI();
  if (fallbackContext) publishHostContext(fallbackContext);
  const fallbackResult = toolResultFromOpenAI();
  if (fallbackResult) publishToolResult(fallbackResult);

  try {
    const initialized = await request<{
      hostContext?: HostContext;
    }>("ui/initialize", {
      appInfo: { name: "Holy Spend", version: "0.6.0" },
      appCapabilities: {
        availableDisplayModes: ["inline", "fullscreen"],
      },
      protocolVersion: "2026-01-26",
    });
    if (initialized?.hostContext) publishHostContext(initialized.hostContext);
    notify("ui/notifications/initialized");
    reportIntrinsicSize();
  } catch (error) {
    // ChatGPT's window.openai compatibility surface can still support the
    // widget if a host does not implement the latest initialization handshake.
    console.warn("MCP Apps initialization failed; using host compatibility APIs.", error);
  }
}

const connection = isDemoMode ? Promise.resolve() : initializeBridge();

export function subscribeToToolResults(listener: (result: ToolResult) => void): () => void {
  listeners.add(listener);
  if (latestToolResult) listener(latestToolResult);
  return () => listeners.delete(listener);
}

export function subscribeToHostContext(listener: (context: HostContext) => void): () => void {
  hostContextListeners.add(listener);
  if (isDemoMode) {
    const params = new URLSearchParams(window.location.search);
    const hashParams = new URLSearchParams(window.location.hash.slice(1));
    listener({
      theme: params.get("theme") === "dark" ? "dark" : "light",
      locale: "en-CA",
      displayMode: params.get("mode") || hashParams.get("mode") || "fullscreen",
    });
  } else if (latestHostContext) {
    listener(latestHostContext);
  }
  return () => hostContextListeners.delete(listener);
}

export async function callTool(
  name: string,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  if (isDemoMode) return demoCallTool(name, args);
  await connection;
  const result = await request<ToolResult>("tools/call", {
    name,
    arguments: args,
  });
  if (result.isError) {
    const message = result.content?.find((part) => part.type === "text")?.text;
    throw new Error(message || `${name} failed`);
  }
  return result;
}

export async function requestFullscreen(): Promise<void> {
  if (isDemoMode) return;
  if (window.openai?.requestDisplayMode) {
    await window.openai.requestDisplayMode({ mode: "fullscreen" });
    return;
  }
  await connection;
  await request("ui/request-display-mode", { mode: "fullscreen" });
}

export async function openPrivateUrl(url: string): Promise<void> {
  if (isDemoMode) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  await connection;
  await request("ui/open-link", { url });
}

export function persistWidgetState(state: Record<string, unknown>): void {
  window.openai?.setWidgetState?.(state);
}

export function structured<T>(result: ToolResult): T {
  const value = result.structuredContent;
  if (!value) throw new Error("Tool returned no structured content");
  if ("result" in value && typeof value.result === "object" && value.result !== null) {
    return value.result as T;
  }
  return value as T;
}

export function privateMeta<T>(result: ToolResult, key: string): T | undefined {
  const namespace = result._meta?.dailyExpenseTracker;
  if (!namespace || typeof namespace !== "object") return undefined;
  return (namespace as Record<string, unknown>)[key] as T | undefined;
}
