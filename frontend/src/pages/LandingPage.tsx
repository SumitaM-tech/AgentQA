import { Bug, Camera, Compass, GitBranch, Radar, ScrollText, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

const STEPS = [
  ["Give it a URL", "Point AgentQA at the web app you want tested. Private and local addresses are blocked unless you opt in."],
  ["Define your testing goal", "Describe what matters in plain language, e.g. “Thoroughly test the checkout flow.”"],
  ["Agent explores autonomously", "A Gemini-driven agent chooses actions from a fixed, validated set; Playwright performs them in a real browser."],
  ["Bugs are verified", "Findings are re-checked and, when safe, reproduced before they are reported."],
  ["Get evidence-backed reports", "Every bug carries steps, screenshots, console and network evidence, ready to export."],
];
const FEATURES = [
  [Compass, "Autonomous exploration", "Explores pages, forms and flows on its own, remembering what it has already tried."],
  [Sparkles, "AI-powered reasoning", "Gemini proposes the next action and reviews unexpected behaviour as a critic."],
  [Radar, "Live browser testing", "Watch screenshots and agent activity stream in as the run progresses."],
  [GitBranch, "Exploration graph", "See every discovered state and transition as an interactive graph."],
  [Bug, "Bug intelligence", "Severity with an explanation, confidence scores, de-duplication and verification status."],
  [ScrollText, "Evidence-based reports", "Export bug reports as Markdown or JSON, with screenshots and logs attached."],
] as const;

export default function LandingPage() {
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-card focus:p-2">Skip to content</a>
      <header className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
        <div className="flex items-center gap-2 font-semibold"><span className="grid h-8 w-8 place-items-center rounded-lg bg-primary/20 text-primary"><Radar className="h-4 w-4" /></span>AgentQA <span className="font-normal text-muted-foreground">Cloud</span></div>
        <nav aria-label="Primary" className="flex items-center gap-2">
          <Link to="/dashboard" className="rounded-lg px-3 py-2 text-sm text-muted-foreground hover:text-foreground">Dashboard</Link>
          <Link to="/runs/new"><Button variant="primary" size="sm">Start a QA Run</Button></Link>
        </nav>
      </header>
      <main id="main">
        <section className="mx-auto max-w-4xl px-4 py-20 text-center">
          <p className="mb-4 inline-block rounded-full border border-border px-3 py-1 text-xs text-muted-foreground">Open-source autonomous QA</p>
          <h1 className="text-4xl font-semibold tracking-tight sm:text-6xl">Autonomous QA<br />for the Modern Web</h1>
          <p className="mx-auto mt-6 max-w-xl text-lg text-muted-foreground">Let an AI agent explore, test, and discover bugs in your application.</p>
          <div className="mt-8 flex justify-center gap-3">
            <Link to="/runs/new"><Button variant="primary" size="lg">Start a QA Run</Button></Link>
            <a href="#how"><Button size="lg">How it works</Button></a>
          </div>
        </section>
        <section id="how" className="mx-auto max-w-6xl px-4 py-12" aria-labelledby="how-h">
          <h2 id="how-h" className="mb-8 text-center text-2xl font-semibold">How It Works</h2>
          <ol className="grid gap-4 md:grid-cols-5">
            {STEPS.map(([t, d], i) => (
              <li key={t} className="glass p-4">
                <span className="mb-3 grid h-7 w-7 place-items-center rounded-full bg-primary/20 text-sm font-semibold text-primary" aria-hidden>{i + 1}</span>
                <h3 className="text-sm font-semibold">{t}</h3>
                <p className="mt-1.5 text-xs text-muted-foreground">{d}</p>
              </li>
            ))}
          </ol>
        </section>
        <section className="mx-auto max-w-6xl px-4 py-12" aria-labelledby="feat-h">
          <h2 id="feat-h" className="mb-8 text-center text-2xl font-semibold">What you get</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(([Icon, t, d]) => (
              <div key={t} className="glass p-5">
                <Icon className="mb-3 h-5 w-5 text-primary" aria-hidden />
                <h3 className="font-semibold">{t}</h3>
                <p className="mt-1.5 text-sm text-muted-foreground">{d}</p>
              </div>
            ))}
          </div>
        </section>
        <section className="mx-auto max-w-3xl px-4 py-16 text-center">
          <Camera className="mx-auto mb-3 h-6 w-6 text-primary" aria-hidden />
          <h2 className="text-2xl font-semibold">Try it on the bundled demo shop</h2>
          <p className="mt-2 text-muted-foreground">The repository includes a small demo application with intentional bugs, so you can watch a real run end to end.</p>
          <Link to="/runs/new" className="mt-6 inline-block"><Button variant="primary" size="lg">Start a QA Run</Button></Link>
        </section>
      </main>
      <footer className="border-t border-border py-6 text-center text-xs text-muted-foreground">AgentQA Cloud — findings are generated by an AI agent and should be reviewed by a human.</footer>
    </div>
  );
}
