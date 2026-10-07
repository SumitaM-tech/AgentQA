import { forwardRef, type InputHTMLAttributes, type LabelHTMLAttributes, type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-lg border border-border bg-background/60 px-3 text-sm placeholder:text-muted-foreground/60 " +
  "transition-colors focus-visible:border-primary/60 disabled:opacity-50";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn(FIELD, "h-10", className)} {...p} />
));
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...p }, ref) => <textarea ref={ref} className={cn(FIELD, "py-2 min-h-[88px] resize-y", className)} {...p} />,
);
Textarea.displayName = "Textarea";

export function Label({ className, ...p }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("mb-1.5 block text-xs font-medium text-muted-foreground", className)} {...p} />;
}
