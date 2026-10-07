import { Bug as BugIcon, CircleDashed, Crosshair, Maximize2, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlowProvider, useReactFlow,
  type Edge, type Node, type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { Link } from "react-router-dom";

import { SeverityBadge } from "@/components/SeverityBadge";
import { ScreenshotPreview } from "@/components/ScreenshotPreview";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { layoutStates, mergeEdges } from "@/lib/graphLayout";
import { cn, formatDateTime, pathOf, truncate } from "@/lib/utils";
import type { Bug, Graph, UIEdge, UIState } from "@/types";

type Status = "current" | "visited" | "unexplored";
interface NodeData { state: UIState; status: Status; outgoing: number; dim: boolean }

const STATUS_LABEL: Record<Status, string> = { current: "Current", visited: "Visited", unexplored: "Has untried actions" };

function StateNode({ data, selected }: NodeProps<NodeData>) {
  const s = data.state;
  return (
    <div className={cn(
      "w-[230px] rounded-xl border bg-card p-3 text-left shadow-lg transition-opacity",
      selected ? "border-primary" : "border-border",
      s.bug_count > 0 && "border-red-500/70",
      data.status === "unexplored" && "border-dashed",
      data.status === "current" && "ring-2 ring-emerald-500/70",
      data.dim && "opacity-25",
    )}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-0 !bg-muted-foreground" />
      <div className="flex items-start justify-between gap-2">
        <p className="truncate text-sm font-medium">{truncate(s.title || "Untitled", 24)}</p>
        {s.bug_count > 0 && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-red-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-red-700 dark:text-red-300" aria-label={`${s.bug_count} bugs`}>
            <BugIcon className="h-3 w-3" aria-hidden />{s.bug_count}
          </span>
        )}
      </div>
      <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">{truncate(pathOf(s.url), 30)}</p>
      <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          {data.status === "current" ? <Crosshair className="h-3 w-3" aria-hidden /> : data.status === "unexplored" ? <CircleDashed className="h-3 w-3" aria-hidden /> : null}
          {STATUS_LABEL[data.status]}
        </span>
        <span>visits {s.visit_count} · out {data.outgoing}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-0 !bg-muted-foreground" />
    </div>
  );
}
const nodeTypes = { state: StateNode };

function Detail({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="grid grid-cols-[110px_1fr] gap-2 py-1 text-xs"><dt className="text-muted-foreground">{k}</dt><dd className="min-w-0 break-words">{v}</dd></div>;
}

function Inner({ graph, bugs }: { graph: Graph; bugs: Bug[] }) {
  const { fitView, setCenter, getNode } = useReactFlow();
  const [selNode, setSelNode] = useState<string | null>(null);
  const [selEdge, setSelEdge] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const byId = useMemo(() => new Map(graph.states.map((s) => [s.id, s])), [graph.states]);
  const merged = useMemo(() => mergeEdges(graph.edges), [graph.edges]);
  const positions = useMemo(() => layoutStates(graph.states, merged), [graph.states, merged]);

  // Per-state outgoing action count and tried elements -> "unexplored" = interactive elements never exercised.
  const info = useMemo(() => {
    const out = new Map<string, { n: number; tried: Set<string> }>();
    for (const e of graph.edges) {
      const o = out.get(e.source_state_id) ?? { n: 0, tried: new Set<string>() };
      o.n += 1;
      if (e.target_element_id) o.tried.add(e.target_element_id);
      out.set(e.source_state_id, o);
    }
    return out;
  }, [graph.edges]);

  const q = query.trim().toLowerCase();
  const nodes: Node<NodeData>[] = useMemo(() => graph.states.map((s) => {
    const o = info.get(s.id);
    const untried = s.interactive_elements.filter((el) => !o?.tried.has(el.id)).length;
    const status: Status = s.id === graph.current_state_id ? "current" : untried > 0 ? "unexplored" : "visited";
    const match = !q || s.title.toLowerCase().includes(q) || s.url.toLowerCase().includes(q) || s.fingerprint.startsWith(q);
    return { id: s.id, type: "state", position: positions[s.id] ?? { x: 0, y: 0 }, data: { state: s, status, outgoing: o?.n ?? 0, dim: !match } };
  }), [graph.states, graph.current_state_id, info, positions, q]);

  const edges: Edge[] = useMemo(() => merged.map((m) => {
    const last = m.edges[m.edges.length - 1];
    const bad = m.edges.some((e) => e.verdict === "action_failed" || e.verdict === "bug");
    return {
      id: m.id, source: m.source, target: m.target,
      // Labels only for small graphs or the selected edge; dense graphs stay readable.
      label: merged.length <= 8 || selEdge === m.id ? truncate(last.action_label.replace(/^(Clicking|Opening) /, ""), 22) + (m.edges.length > 1 ? ` +${m.edges.length - 1}` : "") : undefined,
      type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed, color: bad ? "#f87171" : "#64748b" },
      style: { stroke: bad ? "#f87171" : "#64748b", strokeWidth: selEdge === m.id ? 2.6 : 1.2, opacity: merged.length > 8 && selEdge !== m.id ? 0.55 : 1 },
      labelStyle: { fontSize: 10, fill: "#94a3b8" }, labelBgStyle: { fill: "transparent" },
    };
  }), [merged, selEdge]);

  useEffect(() => {
    const t = window.setTimeout(() => fitView({ padding: 0.25, duration: 250, maxZoom: 1 }), 200);
    return () => window.clearTimeout(t);
  }, [graph.states.length, fitView]);

  const node = selNode ? byId.get(selNode) : undefined;
  const edge = selEdge ? merged.find((m) => m.id === selEdge) : undefined;
  const nodeBugs = node ? bugs.filter((b) => b.state_key === node.fingerprint) : [];
  const nodeInfo = node ? info.get(node.id) : undefined;
  const untried = node ? node.interactive_elements.filter((el) => !nodeInfo?.tried.has(el.id)) : [];

  const focusMatch = () => {
    const hit = nodes.find((n) => !n.data.dim);
    const nd = hit && getNode(hit.id);
    if (hit && nd) { setSelNode(hit.id); setSelEdge(null); setCenter(nd.position.x + 115, nd.position.y + 40, { zoom: 1, duration: 300 }); }
  };

  return (
    <div className="grid h-full min-h-[520px] grid-rows-[auto_1fr] lg:grid-cols-[1fr_340px] lg:grid-rows-1">
      <div className="relative min-h-[420px]">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} minZoom={0.1} maxZoom={1.8} fitView fitViewOptions={{ padding: 0.25, maxZoom: 1 }}
          onNodeClick={(_, n) => { setSelNode(n.id); setSelEdge(null); }} onEdgeClick={(_, e) => { setSelEdge(e.id); setSelNode(null); }}
          onPaneClick={() => { setSelNode(null); setSelEdge(null); }} nodesConnectable={false} onlyRenderVisibleElements proOptions={{ hideAttribution: true }}>
          <Background gap={24} color="hsl(var(--border))" />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable nodeColor={(n) => ((n.data as NodeData).state.bug_count ? "#f87171" : "#64748b")} />
        </ReactFlow>
        <div className="absolute left-3 top-3 flex items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden />
            <Input aria-label="Search states" placeholder="Search states…" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && focusMatch()} className="h-9 w-48 bg-card pl-8" />
          </div>
          <Button size="sm" onClick={() => fitView({ padding: 0.25, duration: 250, maxZoom: 1 })}><Maximize2 className="h-3.5 w-3.5" /> Fit</Button>
        </div>
        <p className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-card/80 px-2 py-1 text-[10px] text-muted-foreground">
          Green ring = current · dashed = untried actions · red border = has bugs
        </p>
      </div>

      <aside aria-label="Selection details" className="overflow-y-auto border-t border-border p-4 lg:border-l lg:border-t-0">
        {!node && !edge && <p className="text-sm text-muted-foreground">Select a state or a transition to see its details.</p>}
        {node && (
          <div className="space-y-3">
            <div className="flex items-start justify-between gap-2"><h3 className="text-sm font-semibold">State details</h3>
              <Button size="sm" variant="ghost" onClick={() => setSelNode(null)} aria-label="Clear selection"><X className="h-4 w-4" /></Button></div>
            <dl className="divide-y divide-border">
              <Detail k="Title" v={node.title || "—"} />
              <Detail k="URL" v={<span className="font-mono">{node.url}</span>} />
              <Detail k="State ID" v={<span className="font-mono">{node.fingerprint.slice(0, 16)}</span>} />
              <Detail k="First discovered" v={`${formatDateTime(node.created_at)} (step ${node.discovered_at_step})`} />
              <Detail k="Last visited" v={formatDateTime(node.last_seen_at)} />
              <Detail k="Visit count" v={node.visit_count} />
              <Detail k="Depth" v={node.depth} />
            </dl>
            <section><h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Interactive elements ({node.interactive_elements.length})</h4>
              <ul className="max-h-32 space-y-0.5 overflow-auto text-xs">{node.interactive_elements.map((el) => <li key={el.id}><span className="text-muted-foreground">{el.role}</span> {el.name || "(unnamed)"}</li>)}</ul></section>
            <section><h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Available (untried) actions</h4>
              {untried.length ? <ul className="max-h-24 space-y-0.5 overflow-auto text-xs">{untried.map((el) => <li key={el.id}>{el.role} “{el.name || "unnamed"}”</li>)}</ul> : <p className="text-xs text-muted-foreground">All known elements were tried.</p>}</section>
            <section><h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Associated bugs</h4>
              {nodeBugs.length ? <ul className="space-y-1.5">{nodeBugs.map((b) => (
                <li key={b.id}><Link to={`/bugs/${b.id}`} className="flex items-center gap-2 text-xs hover:text-primary"><SeverityBadge severity={b.severity} /><span className="truncate">{b.title}</span></Link></li>))}</ul>
                : <p className="text-xs text-muted-foreground">None.</p>}</section>
            <ScreenshotPreview src={node.screenshot_url} alt={`Screenshot of ${node.title || node.url}`} />
          </div>
        )}
        {edge && (
          <div className="space-y-3">
            <div className="flex items-start justify-between"><h3 className="text-sm font-semibold">Transition{edge.edges.length > 1 ? `s (${edge.edges.length})` : ""}</h3>
              <Button size="sm" variant="ghost" onClick={() => setSelEdge(null)} aria-label="Clear selection"><X className="h-4 w-4" /></Button></div>
            {[...edge.edges].reverse().slice(0, 6).map((e: UIEdge) => (
              <dl key={e.id} className="divide-y divide-border rounded-lg border border-border px-3">
                <Detail k="Action" v={e.action_label || e.action_type} />
                <Detail k="Target" v={e.target_element_id ? <span className="font-mono">{e.target_element_id}</span> : "—"} />
                <Detail k="Source state" v={byId.get(e.source_state_id)?.title ?? "—"} />
                <Detail k="Target state" v={byId.get(e.target_state_id)?.title ?? "—"} />
                <Detail k="Expected" v={e.expected_result || "—"} />
                <Detail k="Actual" v={e.actual_result || "—"} />
                <Detail k="Execution" v={e.verdict === "action_failed" ? "Failed" : "Executed"} />
                <Detail k="Verdict" v={e.verdict ?? "—"} />
                <Detail k="Timestamp" v={formatDateTime(e.created_at)} />
              </dl>
            ))}
          </div>
        )}
      </aside>
    </div>
  );
}

export function ExplorationGraph({ graph, bugs = [] }: { graph: Graph; bugs?: Bug[] }) {
  return <ReactFlowProvider><Inner graph={graph} bugs={bugs} /></ReactFlowProvider>;
}
