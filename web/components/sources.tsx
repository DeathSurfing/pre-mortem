"use client";
import { useState } from "react";
import { ChevronDown } from "lucide-react";
import type { Precedent } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * A citation as a small pill. Hovering shows a preview of the record; clicking expands the full text.
 *
 * Why pills: the evidence is an apparatus, not the argument. Showing three full decision records inline
 * buries the answer. The pill keeps the id visible (so every claim is still attributable at a glance) while
 * the detail stays one interaction away.
 */
export function SourcePill({ p, cited }: { p: Precedent; cited: boolean }) {
  const [open, setOpen] = useState(false);
  const bad = p.outcome === "bad" || p.outcome === "mixed" || p.outcome === "incident" || p.outcome === "degraded";

  const tone = p.is_mirror
    ? "border-[var(--risk-low)] text-risk-low"
    : bad
      ? "border-[var(--risk-high)] text-risk-high"
      : "border-[var(--rule-strong)] text-ink-muted";

  return (
    <span className="group relative inline-block whitespace-nowrap">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title="Click to read the full record"
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-[3px]",
          "font-mono text-[11.5px] transition-colors hover:bg-[var(--paper-sunk)]",
          tone,
        )}
      >
        {p.launch_id}
        <span className="text-[10px] text-ink-faint">ev {p.proof_count}</span>
        {p.is_mirror && <span className="text-[10px]">mirror</span>}
        <ChevronDown className={cn("size-[11px] transition-transform", open && "rotate-180")} />
      </button>

      {/* hover preview: absolutely positioned so it never shifts layout. pointer-events-none so it
          cannot steal the click from the button underneath. */}
      {!open && (
        <span
          role="tooltip"
          className={cn(
            "pointer-events-none absolute left-0 top-full z-30 mt-1.5 w-[min(30rem,80vw)]",
            "rounded-md border border-[var(--rule-strong)] bg-[var(--paper-raised)] p-3",
            "text-[12.5px] leading-relaxed text-ink-soft",
            "opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100",
          )}
          style={{ boxShadow: "0 8px 28px rgba(0,0,0,0.14)" }}
        >
          <span className="mb-1 block font-mono text-[11px] text-ink-faint">
            {p.date} · {p.domain} · {p.decision_type}
          </span>
          {(p.text || "").slice(0, 260)}
          {(p.text || "").length > 260 ? "…" : ""}
        </span>
      )}

      {open && (
        <div className="fade-up mt-2 max-w-[62ch] rounded-md border border-[var(--rule)] bg-[var(--paper-raised)] p-3.5">
          <div className="mb-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-mono text-[12.5px] font-medium text-ink">{p.launch_id}</span>
            <span className="text-[12px] text-ink-faint">{p.date}</span>
            <span className="text-[12px] text-ink-muted">
              {p.domain} · {p.decision_type}
            </span>
            {p.is_mirror ? (
              <span className="text-[12px] font-medium text-risk-low">near-identical, went fine</span>
            ) : bad ? (
              <span className="text-[12px] font-medium text-risk-high">went badly</span>
            ) : p.outcome ? (
              <span className="text-[12px] font-medium text-risk-low">{p.outcome}</span>
            ) : (
              <span className="text-[12px] text-ink-faint">outcome not recorded</span>
            )}
            <span className="ml-auto text-[11.5px] text-ink-faint">evidence {p.proof_count}</span>
          </div>
          {!cited && (
            <div className="mb-1.5 text-[12px] text-ink-faint">
              not cited in the answer above — shown for completeness
            </div>
          )}
          {!p.attribution_ok && (
            <div className="mb-1.5 text-[12px] text-risk-medium">
              this record&apos;s id could not be verified against the corpus, so the id is not quoted
            </div>
          )}
          {p.text && <p className="text-[13px] leading-relaxed text-ink-soft">{p.text}</p>}
        </div>
      )}
    </span>
  );
}

/**
 * The collapsed evidence row: one pill per cited precedent, in citation order.
 * Default state is collapsed, because the answer is the point and the sources are the apparatus.
 */
export function SourceRow({
  precedents,
  citedIds,
}: {
  precedents: Precedent[];
  citedIds: string[];
}) {
  const cited = new Set(citedIds);
  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="label">Sources</span>
        {precedents.map((p) => (
          <SourcePill key={p.launch_id} p={p} cited={cited.has(p.launch_id)} />
        ))}
      </div>
      <p className="mt-2 text-[12px] text-ink-faint">
        hover a source to preview it, click to read the full record
      </p>
    </div>
  );
}


/**
 * Decision ids that appear inline in the prose, rendered as pills.
 *
 * Why: the answer names ids in sentences ("cost us 6.2 points in D-2025-0002 and D-2025-0013"), and a bare
 * mono id there is a dead end — the reader has to hunt for the pill row below. Turning inline mentions into
 * the same pill means any id you can read, you can hover for the preview and click for the full record.
 *
 * Ids that are NOT in the precedent set (e.g. one the corpus check could not verify) render as plain mono
 * text, so nothing is silently dressed up as evidence.
 */
export function AnnotatedProse({
  text,
  precedents,
  className,
}: {
  text: string;
  precedents: Precedent[];
  className?: string;
}) {
  const byId = new Map(precedents.map((p) => [p.launch_id, p]));

  // Decision ids look like D-2025-0013 / L-2026-0412. Word-boundary guarded so ids inside filenames or
  // longer tokens are not matched.
  const parts = text.split(/(\b[DLA]-\d{4}-\d{3,4}\b)/g);

  return (
    <span className={className}>
      {parts.map((part, i) => {
        const hit = byId.get(part);
        if (hit) {
          return (
            <span key={i} className="mx-0.5 inline-block align-baseline">
              <SourcePill p={hit} cited />
            </span>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </span>
  );
}
