import { Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { formatDateTime, formatDuration, hostOf, truncate } from "@/lib/utils";
import { isActive, type Run } from "@/types";

export function RunTable({ runs, onDelete }: { runs: Run[]; onDelete?: (r: Run) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">QA runs</caption>
        <thead className="text-xs text-muted-foreground">
          <tr className="border-b border-border">
            {["Run ID", "Target", "Goal", "Status", "Duration", "Steps", "States", "Bugs", "Created", ...(onDelete ? [""] : [])].map((h, i) => (
              <th key={i} scope="col" className="whitespace-nowrap px-4 py-2 font-medium">{h || <span className="sr-only">Actions</span>}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="border-b border-border/60 transition-colors hover:bg-muted/30">
              <td className="px-4 py-2.5 font-mono text-xs"><Link to={`/runs/${r.id}`} className="hover:text-primary" title={r.id}>{r.id.slice(0, 8)}</Link></td>
              <td className="px-4 py-2.5 font-medium">{hostOf(r.target_url)}</td>
              <td className="max-w-[240px] px-4 py-2.5 text-muted-foreground" title={r.goal}>{truncate(r.goal, 50)}</td>
              <td className="px-4 py-2.5"><StatusBadge status={r.status} /></td>
              <td className="px-4 py-2.5 tabular-nums">{formatDuration(r.duration_seconds)}</td>
              <td className="px-4 py-2.5 tabular-nums">{r.steps_taken}/{r.max_steps}</td>
              <td className="px-4 py-2.5 tabular-nums">{r.states_count}</td>
              <td className="px-4 py-2.5 tabular-nums">{r.bugs_count}</td>
              <td className="whitespace-nowrap px-4 py-2.5 text-muted-foreground">{formatDateTime(r.created_at)}</td>
              {onDelete && (
                <td className="px-2 py-2.5">
                  <Button variant="ghost" size="sm" disabled={isActive(r.status)} onClick={() => onDelete(r)} aria-label={`Delete run ${r.id.slice(0, 8)}`}><Trash2 className="h-3.5 w-3.5" /></Button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
