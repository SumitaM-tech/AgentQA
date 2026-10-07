import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("UI error:", error, info.componentStack); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="mx-auto mt-16 max-w-md space-y-3 rounded-xl border border-danger/30 bg-danger/10 p-6 text-center">
        <p className="font-semibold">Something went wrong in the interface.</p>
        <p className="text-sm text-muted-foreground">{this.state.error.message}</p>
        <Button onClick={() => { this.setState({ error: null }); window.location.assign("/dashboard"); }}>Back to dashboard</Button>
      </div>
    );
  }
}
