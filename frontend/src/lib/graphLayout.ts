import type { UIEdge, UIState } from "@/types";

export interface MergedEdge {
  id: string;
  source: string;
  target: string;
  edges: UIEdge[];
}

/** Collapse parallel edges (same source -> target) so big runs stay readable and fast. */
export function mergeEdges(edges: UIEdge[]): MergedEdge[] {
  const map = new Map<string, MergedEdge>();
  for (const e of edges) {
    const key = `${e.source_state_id}->${e.target_state_id}`;
    const hit = map.get(key);
    if (hit) hit.edges.push(e);
    else map.set(key, { id: key, source: e.source_state_id, target: e.target_state_id, edges: [e] });
  }
  return [...map.values()];
}

const NODE_W = 230;
const NODE_H = 96;
const GAP_X = 50;
const GAP_Y = 90;

/** Layered layout: depth = shortest hop count from the first-discovered state; centred per layer. */
export function layoutStates(states: UIState[], edges: MergedEdge[]): Record<string, { x: number; y: number }> {
  if (states.length === 0) return {};
  const ordered = [...states].sort((a, b) => a.discovered_at_step - b.discovered_at_step);
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    if (e.source === e.target) continue;
    adj.set(e.source, [...(adj.get(e.source) ?? []), e.target]);
  }
  const level = new Map<string, number>();
  const queue: string[] = [];
  const visit = (id: string, l: number) => { level.set(id, l); queue.push(id); };
  visit(ordered[0].id, 0);
  for (let head = 0; head < queue.length || level.size < ordered.length; ) {
    if (head >= queue.length) {
      const orphan = ordered.find((s) => !level.has(s.id));
      if (!orphan) break;
      visit(orphan.id, 0);
    }
    const cur = queue[head++];
    for (const next of adj.get(cur) ?? []) if (!level.has(next)) visit(next, (level.get(cur) ?? 0) + 1);
  }
  const layers = new Map<number, string[]>();
  for (const s of ordered) {
    const l = level.get(s.id) ?? 0;
    layers.set(l, [...(layers.get(l) ?? []), s.id]);
  }
  const widest = Math.max(...[...layers.values()].map((v) => v.length));
  const totalW = widest * (NODE_W + GAP_X);
  const pos: Record<string, { x: number; y: number }> = {};
  for (const [l, ids] of layers) {
    const rowW = ids.length * (NODE_W + GAP_X);
    ids.forEach((id, i) => {
      pos[id] = { x: (totalW - rowW) / 2 + i * (NODE_W + GAP_X), y: l * (NODE_H + GAP_Y) };
    });
  }
  return pos;
}
