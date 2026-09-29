"use client";
import { useState } from "react";
import { CircleCheck, ClipboardCheck, Loader2 } from "lucide-react";
import { promptStore, type UnresolvedDecision } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * "What actually happened?" for decisions already in the history.
 *
 * Why this exists: the verdict comes from recorded outcomes, so a decision that was added and never
 * followed up can support a review as context but can never become evidence. Without this panel every
 * added decision stays permanently result-less. It is shown once per review, and only for decisions the
 * user themselves committed, because they are the only ones who can know.
 */
export function ResolveDecisions({
  items,
  onResolved,
  onDismiss,
}: {
  items: UnresolvedDecision[];
  onResolved: (id: string, outcome: string) => void;
  onDismiss: () => void;
}) {
  const rows = Array.isArray(items) ? items.filter(Boolean) : [];
  const [openFor, setOpenFor] = useState<string | null>(rows[0]?.id ?? null);
  const [outcome, setOutcome] = useState("");
  const [result, setResult] = useState("");
  const [lesson, setLesson] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string[]>([]);

  if (rows.length === 0) return null;

  const current = rows.find((r) => r.id === openFor && !done.includes(r.id)) ?? null;

  async function save() {
    if (!current) return;
    if (!outcome) { setError("Pick how it went."); return; }
    setBusy(true); setError(null);
    try {
      await promptStore.resolveDecision({ id: current.id, outcome, result, lesson });
      setDone((d) => [...d, current.id]);
      onResolved(current.id, outcome);
      // Move to the next unresolved one without closing the panel: a user who knows one outcome usually
      // knows the others.
      const next = rows.find((r) => r.id !== current.id && !done.includes(r.id));
      setOpenFor(next?.id ?? null);
      setOutcome(""); setResult(""); setLesson("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const remaining = rows.filter((r) => !done.includes(r.id));

  return (
    <section className="mt-6 border border-[var(--rule-strong)] bg-paper-raised">
      <div className="flex items-start gap-3 border-b border-rule px-4 py-3">
        <ClipboardCheck className="mt-[2px] size-[14px] shrink-0 text-accent" strokeWidth={2} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] text-ink">
            {remaining.length === 1
              ? "One decision you added has no outcome recorded"
              : `${remaining.length} decisions you added have no outcome recorded`}
          </p>
          <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
            Until an outcome is known, a decision can be recalled as context but cannot count as evidence.
          </p>
        </div>
        <button
          onClick={onDismiss}
          className="min-h-[32px] shrink-0 rounded-md px-2 text-[12px] text-ink-faint transition-colors hover:bg-[var(--paper-sunk)] hover:text-ink"
        >
          Later
        </button>
      </div>

      {done.length > 0 && (
        <p className="flex items-center gap-1.5 border-b border-rule bg-[var(--risk-low-wash)] px-4 py-2.5 text-[12.5px] text-ink-soft">
          <CircleCheck className="size-[13px] text-risk-low" strokeWidth={2.2} />
          {done.length === 1 ? "Outcome recorded." : `${done.length} outcomes recorded.`} It can now count as
          evidence.
        </p>
      )}

      {rows.length > 1 && remaining.length > 1 && (
        <div className="border-b border-rule px-4 py-2.5">
          <ul className="space-y-1">
            {remaining.map((r) => (
              <li key={r.id}>
                <button
                  onClick={() => { setOpenFor(r.id); setError(null); }}
                  className={cn(
                    "flex w-full min-h-[30px] items-center gap-2 rounded px-1 text-left text-[12px] transition-colors",
                    r.id === current?.id ? "text-ink" : "text-ink-muted hover:text-ink",
                  )}
                >
                  <span className={cn("inline-block size-[6px] shrink-0 rounded-full",
                    r.id === current?.id ? "bg-accent" : "bg-[var(--rule-strong)]")} />
                  <span className="truncate">{r.prompt.slice(0, 90)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {current && (
        <div className="px-4 py-3">
          {rows.length > 1 && (
            <p className="mb-2 text-[12.5px] text-ink">What happened to: <span className="text-ink-muted">{current.prompt.slice(0, 110)}</span></p>
          )}
          <div className="space-y-3">
            <div>
              <span className="block text-[12.5px] text-ink-soft">How did it go?</span>
              <div className="mt-1.5 inline-flex rounded-md border border-[var(--rule-strong)] p-[2px]">
                {([["good", "Went well"], ["mixed", "Mixed"], ["bad", "Went badly"]] as const).map(([v, label]) => (
                  <button
                    key={v}
                    onClick={() => setOutcome(v)}
                    className={cn(
                      "min-h-[38px] rounded-[5px] px-3 text-[12.5px] transition-colors",
                      outcome === v ? "bg-[var(--paper-sunk)] text-ink" : "text-ink-muted hover:text-ink",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <label className="block">
              <span className="block text-[12.5px] text-ink-soft">What actually happened?</span>
              <textarea
                rows={2}
                value={result}
                onChange={(e) => setResult(e.target.value)}
                placeholder="In your own words. This becomes the evidence a future review cites."
                className="mt-1.5 w-full resize-y rounded-md border border-[var(--rule-strong)] bg-paper-raised px-3 py-2 text-[13.5px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
              />
            </label>
            <label className="block">
              <span className="block text-[12.5px] text-ink-soft">Anything worth remembering? (optional)</span>
              <input
                value={lesson}
                onChange={(e) => setLesson(e.target.value)}
                className="mt-1.5 w-full rounded-md border border-[var(--rule-strong)] bg-paper-raised px-3 py-2 text-[13.5px] text-ink focus:border-accent focus:outline-none"
              />
            </label>
          </div>
        </div>
      )}

      {error && (
        <p className="border-t border-rule bg-[var(--risk-high-wash)] px-4 py-2.5 text-[12.5px] text-ink-soft">
          Could not save: {error}
        </p>
      )}

      {current && (
        <div className="flex flex-wrap items-center gap-2 border-t border-rule px-4 py-3">
          <button
            onClick={save}
            disabled={busy}
            className="flex min-h-[38px] items-center gap-1.5 rounded-md bg-accent px-4 text-[13px] text-white transition-opacity hover:bg-accent-deep disabled:opacity-40"
          >
            {busy ? <Loader2 className="size-[14px] animate-spin" strokeWidth={2} />
                  : <ClipboardCheck className="size-[14px]" strokeWidth={2.2} />}
            {busy ? "Saving" : "Record outcome"}
          </button>
        </div>
      )}
    </section>
  );
}
