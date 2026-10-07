import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

export function CopyButton({ text, label, size = "sm" }: { text: string; label: string; size?: "sm" | "md" }) {
  const [done, setDone] = useState(false);
  const { toast } = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      toast(`${label} copied`, "success");
      window.setTimeout(() => setDone(false), 1500);
    } catch {
      toast("Clipboard is not available in this browser context.", "error");
    }
  };
  return (
    <Button variant="ghost" size={size} onClick={copy} aria-label={`Copy ${label}`} title={`Copy ${label}`}>
      {done ? <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
    </Button>
  );
}
