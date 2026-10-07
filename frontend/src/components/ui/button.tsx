import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-primary-foreground hover:bg-primary/90 shadow-lg shadow-primary/20",
  secondary: "bg-muted text-foreground hover:bg-muted/70 border border-border",
  ghost: "text-muted-foreground hover:text-foreground hover:bg-muted/60",
  danger: "bg-danger/15 text-danger hover:bg-danger/25 border border-danger/30",
};
const SIZES: Record<Size, string> = { sm: "h-8 px-3 text-xs", md: "h-9 px-4 text-sm", lg: "h-11 px-6 text-sm" };

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> { variant?: Variant; size?: Size }

export const Button = forwardRef<HTMLButtonElement, Props>(({ className, variant = "secondary", size = "md", ...p }, ref) => (
  <button
    ref={ref}
    className={cn(
      "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none",
      VARIANTS[variant], SIZES[size], className,
    )}
    {...p}
  />
));
Button.displayName = "Button";
