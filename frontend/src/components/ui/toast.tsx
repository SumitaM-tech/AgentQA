import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

type Kind = "success" | "error" | "info";
interface Toast { id: number; kind: Kind; message: string }
interface Ctx { toast: (message: string, kind?: Kind) => void }

const ToastCtx = createContext<Ctx>({ toast: () => undefined });
export const useToast = () => useContext(ToastCtx);

const ICON = { success: CheckCircle2, error: XCircle, info: Info };
const TONE = { success: "text-emerald-600 dark:text-emerald-400", error: "text-red-600 dark:text-red-400", info: "text-sky-600 dark:text-sky-400" };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const next = useRef(1);
  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), []);
  const toast = useCallback((message: string, kind: Kind = "info") => {
    const id = next.current++;
    setItems((l) => [...l.slice(-3), { id, kind, message }]);
    window.setTimeout(() => dismiss(id), kind === "error" ? 7000 : 4000);
  }, [dismiss]);
  const value = useMemo(() => ({ toast }), [toast]);
  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2" role="region" aria-label="Notifications" aria-live="polite">
        {items.map((t) => {
          const Icon = ICON[t.kind];
          return (
            <div key={t.id} role={t.kind === "error" ? "alert" : "status"} className="glass pointer-events-auto flex items-start gap-2.5 p-3 text-sm shadow-xl">
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${TONE[t.kind]}`} aria-hidden />
              <p className="min-w-0 flex-1 break-words">{t.message}</p>
              <button onClick={() => dismiss(t.id)} aria-label="Dismiss notification" className="text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}
