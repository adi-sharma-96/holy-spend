import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { HostedTracker, isHostedTrackerPage } from "./HostedTracker";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import "./styles.css";

const hosted = isHostedTrackerPage();

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppErrorBoundary>
      {hosted ? <HostedTracker /> : <App />}
    </AppErrorBoundary>
  </React.StrictMode>,
);
