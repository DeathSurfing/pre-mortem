"use client";
import { Check, Plus } from "lucide-react";
import type { SimilarPrompt } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The prompt to record this decision, and what past prompts this one resembles.
 *
 * Two jobs in one panel, because they answer the same question ("is this reusable knowledge?"):
 *   1. it shows what past prompts this one resembles, drawn from the vector store rather than from
 *      Hindsight;
 *   2. it asks whether to add the decision that was just reviewed.
 *
 * Nothing here writes to the company's knowledge base directly. "Add decision" opens the capture sheet
 * (`AddDecision`), which collects the summary, rationale, result and lesson a citable record needs; the
 * single write path is that sheet's submit. A prompt is recorded and vectorised automatically either way,
 * so declining still leaves the cross-reference above working next time.
 */
export function CommitPrompt({
  prompt,
  domain,
  decisionType,
  risk,
  similar,
  committed,
  onAdd,
  onDismiss,
}: {
  prompt: string;
  domain?: string;
  decisionType?: string;
  risk?: string;
  similar: SimilarPrompt[];
  committed: boolean;
  onAdd: () => void;
  onDismiss: () => void;
}) {
  // Defensive: `similar` crosses an API boundary, and a non-array here crashed the whole page during
  // hydration (`r.map is not a function`). Normalise once instead of trusting the shape.
  const rows = Array.isArray(similar) ? similar : [];
  // Only genuine neighbours, so the panel never implies a precedent that is not there.
  const matches = rows.filter((s) => s && s.above_cutoff);

  if (committed) {
    return (
      <div className="limit mt-6 flex flex-wrap items-center gap-x-2 gap-y-1 border-l-2 border-risk-low bg-[var(--risk-low-wash)] px-4 py-3 text-[13px] text-ink-soft">
        <Check className="size-[14px] shrink-0 text-risk-low" strokeWidth={2.2} />
        <span>Added to the history. It is now company memory and future reviews can cite it.</span>
      </div>
    );
  }

  return (
    <div className="mt-6 border border-[var(--rule-strong)] bg-paper-raised">
      <div className="flex items-start gap-3 px-4 py-3">
        <Plus className="mt-[2px] size-[14px] shrink-0 text-accent" strokeWidth={2} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] text-ink">Is this a decision the company made?</p>
          <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
            Add it to the history and future reviews can recall it. Recorded for cross-referencing either
            way, so declining loses the record but not the comparison above.
          </p>
        </div>
      </div>

      {matches.length > 0 && (
        <div className="border-t border-rule px-4 py-3">
          <span className="label">Similar prompts asked before</span>
          <ul className="mt-2 space-y-2">
            {matches.map((s) => (
              <li key={s.id} className="text-[12.5px] leading-relaxed text-ink-soft">
                <span className="font-mono text-[11.5px] text-ink-faint">
                  {Math.round(s.similarity * 100)}%
                </span>{" "}
                <span className="text-ink-muted">{s.prompt.slice(0, 150)}</span>
                {s.committed && <span className="ml-1.5 text-[11.5px] text-risk-low">in the knowledge base</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-rule px-4 py-3">
        <button
          onClick={onAdd}
          className={cn(
            "flex min-h-[36px] items-center gap-1.5 rounded-md bg-accent px-3.5 text-[13px] text-white",
            "transition-opacity hover:bg-accent-deep",
          )}
        >
          <Plus className="size-[14px]" strokeWidth={2.2} />
          Add this decision
        </button>
        <button
          onClick={onDismiss}
          className="min-h-[36px] rounded-md px-3.5 text-[13px] text-ink-muted transition-colors hover:bg-[var(--paper-sunk)] hover:text-ink"
        >
          Not a decision
        </button>
      </div>
    </div>
  );
}
