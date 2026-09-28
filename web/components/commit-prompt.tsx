"use client";
import { useState } from "react";
import { Check, Database, X } from "lucide-react";
import type { SimilarPrompt } from "@/lib/api";
import { promptStore } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The commit gate, and the cross-reference beside it.
 *
 * Two jobs in one panel, because they answer the same question ("is this prompt reusable knowledge?"):
 *   1. it shows what past prompts this one resembles, drawn from the vector store rather than from
 *      Hindsight;
 *   2. it asks whether to put this prompt into the company knowledge base.
 *
 * The answer to (2) decides everything. A prompt is recorded and vectorised automatically, but it is NOT
 * company knowledge: `record_and_crossref` never touches Hindsight, and the only caller of `retain` on
 * this path is the Yes button below. So "no" is a real outcome, not a no-op, and the panel says so.
 */
export function CommitPrompt({
  prompt,
  domain,
  decisionType,
  risk,
  similar,
  committed,
  onCommitted,
  onDismiss,
}: {
  prompt: string;
  domain?: string;
  decisionType?: string;
  risk?: string;
  similar: SimilarPrompt[];
  committed: boolean;
  onCommitted: (decisionId: string) => void;
  onDismiss: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Defensive: `similar` crosses an API boundary, and a non-array here crashed the whole page during
  // hydration (`r.map is not a function`). Normalise once instead of trusting the shape.
  const rows = Array.isArray(similar) ? similar : [];
  // Only genuine neighbours, so the panel never implies a precedent that is not there.
  const matches = rows.filter((s) => s && s.above_cutoff);

  async function commit() {
    setBusy(true);
    setError(null);
    try {
      const r = await promptStore.commit({ prompt, domain, decision_type: decisionType, risk });
      onCommitted(r.decision_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (committed) {
    return (
      <div className="limit mt-6 flex flex-wrap items-center gap-x-2 gap-y-1 border-l-2 border-risk-low bg-[var(--risk-low-wash)] px-4 py-3 text-[13px] text-ink-soft">
        <Check className="size-[14px] shrink-0 text-risk-low" strokeWidth={2.2} />
        <span>Committed to the knowledge base. This prompt is now company memory.</span>
      </div>
    );
  }

  return (
    <div className="mt-6 border border-[var(--rule-strong)] bg-paper-raised">
      <div className="flex items-start gap-3 border-b border-rule px-4 py-3">
        <Database className="mt-[2px] size-[14px] shrink-0 text-ink-faint" strokeWidth={1.8} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] text-ink">
            Keep this prompt as company knowledge?
          </p>
          <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
            It has been recorded and vectorised for cross-referencing, but it is not in the knowledge base
            and is not used as evidence. Committing adds it as a decision record.
          </p>
        </div>
        <button
          onClick={onDismiss}
          aria-label="Dismiss without committing"
          className="flex size-8 shrink-0 items-center justify-center rounded-md text-ink-faint transition-colors hover:bg-[var(--paper-sunk)] hover:text-ink"
        >
          <X className="size-[14px]" strokeWidth={2} />
        </button>
      </div>

      {matches.length > 0 && (
        <div className="border-b border-rule px-4 py-3">
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

      {error && (
        <p className="border-b border-rule bg-[var(--risk-high-wash)] px-4 py-2.5 text-[12.5px] text-ink-soft">
          Could not commit: {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 px-4 py-3">
        <button
          onClick={commit}
          disabled={busy}
          className={cn(
            "flex min-h-[36px] items-center gap-1.5 rounded-md bg-accent px-3.5 text-[13px] text-white",
            "transition-opacity hover:bg-accent-deep disabled:opacity-40",
          )}
        >
          <Check className="size-[14px]" strokeWidth={2.2} />
          {busy ? "Committing" : "Yes, commit"}
        </button>
        <button
          onClick={onDismiss}
          disabled={busy}
          className="min-h-[36px] rounded-md px-3.5 text-[13px] text-ink-muted transition-colors hover:bg-[var(--paper-sunk)] hover:text-ink disabled:opacity-40"
        >
          No, discard
        </button>
        <span className="text-[11.5px] text-ink-faint">
          recorded either way, so the cross-reference above stays
        </span>
      </div>
    </div>
  );
}
