"use client";
import { useEffect, useRef, useState } from "react";
import { Loader2, Plus, X } from "lucide-react";
import { promptStore, type DecisionDraft } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Capture a decision the company made, so future reviews can cite it.
 *
 * Why a form and not a single button: a decision is only retrievable later if it is recorded on the same
 * terms as the existing history (see `bizcorpus.Decision`), so it needs a summary, a rationale and a
 * context. A prompt on its own extracts poorly and would come back as a weak, uncitable record.
 *
 * The honesty rule is enforced in the UI as well as the prompt: `result` and `outcome` are blank for a
 * decision that has not happened yet, and the fields say so. A decision being weighed genuinely has no
 * result, and a fabricated one would be a false precedent in the store the product cites.
 */
const BLANK: DecisionDraft = {
  decision: "", rationale: "", result: "", lesson: "", outcome: "",
  owner: "", scale: "", context: "", domain: "", decision_type: "",
};

function Field({
  label, hint, children,
}: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[12.5px] text-ink-soft">{label}</span>
      {hint && <span className="mt-0.5 block text-[11.5px] leading-relaxed text-ink-muted">{hint}</span>}
      <span className="mt-1.5 block">{children}</span>
    </label>
  );
}

const inputCls =
  "w-full rounded-md border border-[var(--rule-strong)] bg-paper-raised px-3 py-2 text-[13.5px] text-ink " +
  "placeholder:text-ink-faint focus:border-accent focus:outline-none";

export function AddDecision({
  prompt,
  promptId,
  domain,
  decisionType,
  risk,
  headline,
  onClose,
  onAdded,
}: {
  prompt: string;
  /** The recorded prompt row this decision came from, so committing can flag it as committed. */
  promptId?: string | null;
  domain?: string;
  decisionType?: string;
  risk?: string;
  headline?: string;
  onClose: () => void;
  onAdded: (decisionId: string) => void;
}) {
  const [draft, setDraft] = useState<DecisionDraft>({ ...BLANK });
  const [domains, setDomains] = useState<string[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const firstField = useRef<HTMLTextAreaElement>(null);

  // Draft once on open, from the review the user is looking at.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await promptStore.draft({ prompt, domain, decision_type: decisionType, risk, headline });
        if (!alive) return;
        // Normalise defensively: a non-object here would crash render, the same way a non-array `similar`
        // once did.
        const d = (r && typeof r.draft === "object" && r.draft) || BLANK;
        setDraft({ ...BLANK, ...d });
        setDomains(Array.isArray(r.domains) ? r.domains : []);
        setTypes(Array.isArray(r.decision_types) ? r.decision_types : []);
        setNote(typeof r.note === "string" ? r.note : "");
      } catch (e) {
        if (!alive) return;
        // Not fatal: the user can fill the form in by hand.
        setDraft({ ...BLANK, decision: prompt, domain: domain ?? "", decision_type: decisionType ?? "" });
        setError(`Could not draft automatically (${String(e)}). Fill it in manually.`);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [prompt, domain, decisionType, risk, headline]);

  // Escape closes, and the page behind does not scroll while the sheet is open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const set = <K extends keyof DecisionDraft>(k: K, v: DecisionDraft[K]) =>
    setDraft((d) => ({ ...d, [k]: v }));

  async function add() {
    if (!draft.decision.trim()) { setError("A decision needs at least a summary line."); return; }
    setBusy(true); setError(null);
    try {
      const r = await promptStore.commit({
        // `id` flags the stored prompt row as committed. Without it the decision still reaches Hindsight,
        // but the prompt stays marked uncommitted in the history store, so the cross-reference panel keeps
        // showing it as not yet in the knowledge base.
        id: promptId ?? null,
        prompt, domain, decision_type: decisionType, risk, draft,
      });
      onAdded(r.decision_id);
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center sm:items-center">
      <div className="absolute inset-0 bg-black/35 backdrop-blur-[2px]" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Add this decision to the history"
        className="relative flex max-h-[92vh] w-full flex-col border border-[var(--rule-strong)] bg-paper-raised sm:max-w-[640px]"
        style={{ boxShadow: "0 18px 50px rgba(0,0,0,0.22)" }}
      >
        <div className="flex shrink-0 items-start gap-3 border-b border-rule px-5 py-4">
          <Plus className="mt-[2px] size-[15px] shrink-0 text-accent" strokeWidth={2} />
          <div className="min-w-0 flex-1">
            <h2 className="font-display text-[17px] text-ink">Add this decision to the history</h2>
            <p className="mt-1 text-[12.5px] leading-relaxed text-ink-muted">
              Stored as a decision record, so future reviews can recall it and cite it by id.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Cancel"
            className="flex size-9 shrink-0 items-center justify-center rounded-md text-ink-faint transition-colors hover:bg-[var(--paper-sunk)] hover:text-ink"
          >
            <X className="size-[15px]" strokeWidth={2} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5" style={{ paddingBottom: "max(20px, env(safe-area-inset-bottom))" }}>
          {loading ? (
            <div className="flex items-center gap-2 py-6 text-[13px] text-ink-muted">
              <Loader2 className="size-[14px] animate-spin" strokeWidth={2} />
              Drafting from the review
            </div>
          ) : (
            <div className="space-y-4">
              {note && (
                <p className="border-l-2 border-[var(--rule-strong)] pl-3 text-[12px] leading-relaxed text-ink-muted">
                  {note}
                </p>
              )}

              <Field label="What is the decision?" hint="One line. This is what a future review will match on.">
                <textarea
                  ref={firstField}
                  rows={2}
                  value={draft.decision}
                  onChange={(e) => set("decision", e.target.value)}
                  placeholder="Acme's renewal discount, agreed without a volume commitment"
                  className={cn(inputCls, "resize-y")}
                />
              </Field>

              <Field label="Why, at the time?" hint="The rationale given in the room, not the one that looks good now.">
                <textarea
                  rows={2}
                  value={draft.rationale}
                  onChange={(e) => set("rationale", e.target.value)}
                  placeholder="Champion asked for a gesture; a competitor came in cheaper."
                  className={cn(inputCls, "resize-y")}
                />
              </Field>

              <Field label="What was going on?" hint="Optional. Scale, pressure, deadlines.">
                <textarea
                  rows={2}
                  value={draft.context}
                  onChange={(e) => set("context", e.target.value)}
                  placeholder="Renewal number already committed to the board."
                  className={cn(inputCls, "resize-y")}
                />
              </Field>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Owner" hint="Optional.">
                  <input value={draft.owner} onChange={(e) => set("owner", e.target.value)}
                         placeholder="Name or team" className={inputCls} />
                </Field>
                <Field label="Amount at stake" hint="Optional.">
                  <input value={draft.scale} onChange={(e) => set("scale", e.target.value)}
                         placeholder="e.g. mid six figures" className={inputCls} />
                </Field>
              </div>

              <div className="border-t border-rule pt-4">
                <p className="mb-3 text-[12.5px] text-ink-soft">
                  What happened
                  <span className="mt-0.5 block text-[11.5px] leading-relaxed text-ink-muted">
                    If this decision has not been carried out yet, leave these blank. A decision still being
                    weighed has no result, and a guessed one would put a false precedent into the history.
                  </span>
                </p>
                <div className="space-y-4">
                  <Field label="Result">
                    <textarea
                      rows={2}
                      value={draft.result}
                      onChange={(e) => set("result", e.target.value)}
                      placeholder="Leave blank if it has not happened yet."
                      className={cn(inputCls, "resize-y")}
                    />
                  </Field>
                  <Field label="Outcome" hint="Only set this if you know how it actually went.">
                    <select value={draft.outcome} onChange={(e) => set("outcome", e.target.value)}
                            className={inputCls}>
                      <option value="">Not recorded yet</option>
                      <option value="good">Went well</option>
                      <option value="mixed">Mixed</option>
                      <option value="bad">Went badly</option>
                    </select>
                  </Field>
                  <Field label="Lesson" hint="Optional. What you would tell yourself next time.">
                    <textarea
                      rows={2}
                      value={draft.lesson}
                      onChange={(e) => set("lesson", e.target.value)}
                      className={cn(inputCls, "resize-y")}
                    />
                  </Field>
                </div>
              </div>

              <div className="grid gap-4 border-t border-rule pt-4 sm:grid-cols-2">
                <Field label="Area" hint="Matched against the existing history.">
                  <select value={draft.domain} onChange={(e) => set("domain", e.target.value)} className={inputCls}>
                    <option value="">Unclassified</option>
                    {domains.map((d) => <option key={d} value={d}>{d}</option>)}
                  </select>
                </Field>
                <Field label="Kind of decision">
                  <select value={draft.decision_type} onChange={(e) => set("decision_type", e.target.value)}
                          className={inputCls}>
                    <option value="">Unspecified</option>
                    {types.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </Field>
              </div>
            </div>
          )}

          {error && (
            <p className="mt-4 border-l-2 border-risk-high bg-[var(--risk-high-wash)] px-3 py-2.5 text-[12.5px] text-ink-soft">
              {error}
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-rule px-5 py-3">
          <button
            onClick={add}
            disabled={busy || loading}
            className={cn(
              "flex min-h-[38px] items-center gap-1.5 rounded-md bg-accent px-4 text-[13px] text-white",
              "transition-opacity hover:bg-accent-deep disabled:opacity-40",
            )}
          >
            {busy ? <Loader2 className="size-[14px] animate-spin" strokeWidth={2} /> : <Plus className="size-[14px]" strokeWidth={2.2} />}
            {busy ? "Adding" : "Add decision"}
          </button>
          <button
            onClick={onClose}
            disabled={busy}
            className="min-h-[38px] rounded-md px-4 text-[13px] text-ink-muted transition-colors hover:bg-[var(--paper-sunk)] hover:text-ink disabled:opacity-40"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
