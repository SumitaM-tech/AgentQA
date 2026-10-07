import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { ToastProvider } from "./components/ui/toast";
import { applyTheme } from "./hooks/useTheme";
import "./index.css";

// Apply the saved theme before first paint to avoid a flash.
try { const t = localStorage.getItem("agentqa-theme"); applyTheme(t === "light" ? "light" : "dark"); } catch { /* storage unavailable */ }

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 2_000 } } });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
