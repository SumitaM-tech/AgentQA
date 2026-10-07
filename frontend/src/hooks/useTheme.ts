import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "agentqa-theme";

function initial(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch { /* storage unavailable */ }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function applyTheme(t: Theme) {
  document.documentElement.classList.toggle("light", t === "light");
  document.documentElement.classList.toggle("dark", t === "dark");
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initial);
  useEffect(() => { applyTheme(theme); }, [theme]);
  const set = useCallback((t: Theme) => {
    try { localStorage.setItem(KEY, t); } catch { /* ignore */ }
    setTheme(t);
  }, []);
  return { theme, setTheme: set };
}
