"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, BookOpen, CircleAlert, CircleCheck, PanelLeft, Plus, TriangleAlert } from "lucide-react";
import {
  api,
  promptStore,
  RateLimitedError,
  streamRedflag,
  type Declined,
  type Ledger,
  type LayaSignals,
  type Opinion,
  type Precedent,
  type PromptPreset,
  type HistoryTurn,
  type GuessBlock,
  type Health,
  type SimilarPrompt,
  type UnresolvedDecision,
} from "@/lib/api";
import { DecisionId, Label } from "@/components/editorial";
import { AnnotatedProse, SourceRow } from "@/components/sources";
import { GuessPanel } from "@/components/guess";
import { Thinking } from "@/components/reasoning";
import { Sidebar } from "@/components/sidebar";
import { CommitPrompt } from "@/components/commit-prompt";
import { AddDecision } from "@/components/add-decision";
import { ContactSales } from "@/components/contact-sales";
import { DEFAULT_SETTINGS, useSettings } from "@/lib/settings";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ atoms */

const RISK_COPY: Record<string, { label: string; tone: string; wash: string }> = {
  high: { label: "High risk", tone: "text-risk-high", wash: "bg-[var(--risk-high-wash)]" },
  medium: { label: "Worth a look", tone: "text-risk-medium", wash: "bg-[var(--risk-medium-wash)]" },
  low: { label: "Low risk", tone: "text-risk-low", wash: "bg-[var(--risk-low-wash)]" },
  unknown: { label: "No precedent", tone: "text-risk-unknown", wash: "bg-[var(--risk-unknown-wash)]" },
};

function RiskMark({ risk }: { risk: string }) {
  const Icon = risk === "high" ? CircleAlert : risk === "medium" ? TriangleAlert : risk === "low" ? CircleCheck : BookOpen;
  const copy = RISK_COPY[risk] ?? RISK_COPY.unknown;
  return (
    <span className={cn("inline-flex items-center gap-1.5 font-medium", copy.tone)}>
      <Icon className="size-[15px]" strokeWidth={2} />
      {copy.label}
    </span>
  );
}

/** A precedent, typeset as a citation: id in mono, outcome as a margin note. */
function Citation({ p }: { p: Precedent }) {
  const bad = p.outcome === "bad" || p.outcome === "mixed" || p.outcome === "incident" || p.outcome === "degraded";
  return (
    <li className="fade-up py-3.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <DecisionId id={p.launch_id} className="font-medium text-ink" />
        <span className="text-[12.5px] text-ink-faint">{p.date}</span>
        <span className="text-[12.5px] text-ink-muted">
          {p.domain} · {p.decision_type}
        </span>
        {p.is_mirror ? (
          <span className="text-[12.5px] font-medium text-risk-low">near-identical, went fine</span>
        ) : bad ? (
          <span className="text-[12.5px] font-medium text-risk-high">went badly</span>
        ) : p.outcome ? (
          <span className="text-[12.5px] font-medium text-risk-low">{p.outcome}</span>
        ) : (
          <span className="text-[12.5px] text-ink-faint">outcome not recorded</span>
        )}
        <span className="ml-auto text-[12px] text-ink-faint" title="how much evidence stands behind this">
          evidence {p.proof_count}
        </span>
      </div>
      {!p.attribution_ok && (
        <div className="mt-1.5 text-[12.5px] text-risk-medium">
          this record&apos;s id could not be verified against the corpus, so the id is not quoted
        </div>
      )}
      {p.text && <p className="mt-2 text-[14px] leading-relaxed text-ink-soft measure">{p.text}</p>}
    </li>
  );
}

function LayaNote({ laya, domain, dtype }: { laya: LayaSignals | null; domain: string; dtype: string }) {
  if (!laya) return null;
  const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);
  const rows: [string, string][] = [
    ["area", `${domain} / ${dtype}`],
    ["certainty", pct(laya.domain_confidence)],
    ["reversibility", laya.reversibility_label ?? "—"],
    ["value given away", pct(laya.gives_value_without_commitment)],
  ];
  return (
    <div className="mt-5">
      <Label>Classified locally · no API call</Label>
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-4">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt className="text-[12px] text-ink-faint">{k}</dt>
            <dd className="font-mono text-[13px] text-ink-soft">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/* ------------------------------------------------------------------ the page */

type Turn = {
  id: string;
  question: string;
  status: string;
  domain?: string;
  dtype?: string;
  laya?: LayaSignals | null;
  risk?: string;
  confidence?: number;
  noPrecedent?: boolean;
  rules?: string;
  precedents?: Precedent[];
  declined?: Declined[];
  streamed: string;
  opinion?: Opinion | null;
  cited?: string[];
  uncited?: string[];
  unverified?: string[];
  guess?: GuessBlock | null;
  /** A follow-up in an existing thread: answered in compact prose, without repeating the whole dossier. */
  followUp?: boolean;
  /** `chat` = conversation with no citations. `query` = a question about the records: cites them, but is
   *  not a verdict on a decision being considered. */
  mode?: "decision" | "chat" | "query";
  /** The model's streamed reasoning trace, shown collapsed. */
  thinking?: string;
  /** Cross-reference result for this prompt, from the vector store. Undefined until `prompt_recorded`. */
  promptId?: string | null;
  similar?: SimilarPrompt[];
  /** Which prompt ids this thread has already committed, so a re-render does not re-ask. */
  committedDecisionId?: string;
  commitDismissed?: boolean;
  /** True while the add-decision sheet is open for this turn. */
  adding?: boolean;
  /** The decision id returned after a successful add. */
  addedDecisionId?: string;
  error?: string;
  busy: boolean;
};

export default function Page() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [unresolved, setUnresolved] = useState<UnresolvedDecision[]>([]);
  /** Set when the server refuses for being out of allowance. Stops every further prompt. */
  const [gate, setGate] = useState<{ limit: number; retryAfter: number } | null>(null);
  /** Published limit, and how many this visit has spent, so the header can show what is left. */
  const [limitUsed, setLimitUsed] = useState(0);
  // Mirrored into a ref so `ask` reads the current value: it is called from callbacks that closed over an
  // older render, and a stale `null` there would let a request through after the gate is up.
  const gateRef = useRef<{ limit: number; retryAfter: number } | null>(null);
  /** Recording a decision from the empty state: the composer, and the text it hands to the sheet. */
  const [recordOpen, setRecordOpen] = useState(false);
  const [recordSeed, setRecordSeed] = useState("");
  const [recordFor, setRecordFor] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [presets, setPresets] = useState<PromptPreset[]>([]);
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const { settings, update } = useSettings();
  const [navOpen, setNavOpen] = useState(false);
  const showEvidence = settings.sourcesOpen;
  // The most recent answer drives the drawer: a no-precedent reply has no calibration to point at.
  const latestNoPrecedent = turns.length > 0 && !!turns[turns.length - 1].noPrecedent;
  /** Published limit, so the header can show what is left before the server refuses. */
  const limitInfo = health?.limits;
  const endRef = useRef<HTMLDivElement>(null);
  const busyRef = useRef(false);
  const turnsRef = useRef<Turn[]>([]);

  useEffect(() => {
    api.prompts().then(setPresets).catch(() => {});
    api.ledger().then(setLedger).catch(() => {});
    api.health().then(setHealth).catch(() => {});
    // Unresolved decisions are fetched for the sidebar, which is where the user closes the loop on them.
    promptStore.unresolved(5).then((r) => setUnresolved(r.items ?? [])).catch(() => {});
  }, []);

  useEffect(() => {
    turnsRef.current = turns;
  }, [turns]);

  useEffect(() => {
    gateRef.current = gate;
  }, [gate]);

  useEffect(() => {
    // Only follow the page while an answer is actually being written, and only for the turn that is
    // streaming. Previously this fired on every `turns` change, so dismissing the add-decision panel (or
    // opening it, or committing) yanked the viewport to the bottom of the page.
    const live = turns[turns.length - 1];
    if (!live || (!live.busy && !live.streamed)) return;
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  async function ask(text: string) {
    const question = text.trim();
    if (!question || busyRef.current) return;
    // Belt and braces: the composer is replaced by the gate when this is set, but a stale keypress or a
    // preset click must not slip a request through either.
    if (gateRef.current) return;
    busyRef.current = true;
    setLimitUsed((n) => n + 1);
    setInput("");
    const id = `${Date.now()}`;
    const patch = (fn: (t: Turn) => Turn) =>
      setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)));

    // The first question opens a new thread and gets the full dossier. Everything after it is a follow-up:
    // same memory, same citations, but no repeated evidence apparatus.
    const isFollowUp = turnsRef.current.length > 0;
    // A follow-up is answered as chat, which emits no precedent events, but it cites decisions from the
    // review it is following up on. Carry those forward so the pills still resolve.
    const carried = [...turnsRef.current].reverse().find((x) => (x.precedents ?? []).length > 0);
    setTurns((prev) => [
      ...prev,
      {
        id,
        question,
        status: "connecting",
        streamed: "",
        busy: true,
        followUp: isFollowUp,
        precedents: isFollowUp ? carried?.precedents : undefined,
        cited: isFollowUp ? carried?.cited : undefined,
      },
    ]);

    // Prior turns become the conversation passed to the backend. The assistant side uses the answer text
    // that was actually shown, so the model sees the same thing the user did.
    const history: HistoryTurn[] = turnsRef.current.flatMap((prev) => {
      const answer = (prev.streamed || prev.opinion?.headline || "").trim();
      const out: HistoryTurn[] = [{ role: "user", content: prev.question }];
      if (answer) out.push({ role: "assistant", content: answer });
      return out;
    });

    try {
      await streamRedflag(question, (e) => {
        if (e.type === "status") patch((t) => ({ ...t, status: e.message }));
        else if (e.type === "classify")
          patch((t) => ({
            ...t,
            domain: e.domain,
            dtype: e.decision_type,
            mode: e.mode ?? "decision",
            followUp: e.follow_up ?? t.followUp,
            laya: e.laya,
            status: e.mode === "chat" ? "replying" : "recalling past decisions",
          }));
        else if (e.type === "reasoning") patch((t) => ({ ...t, thinking: (t.thinking ?? "") + e.text }));
        else if (e.type === "verdict")
          patch((t) => ({ ...t, risk: e.risk, confidence: e.confidence, noPrecedent: e.no_precedent, rules: e.rules, status: "writing the review" }));
        else if (e.type === "precedents") patch((t) => ({ ...t, precedents: e.precedents, declined: e.declined }));
        else if (e.type === "delta") patch((t) => ({ ...t, streamed: t.streamed + e.text }));
        else if (e.type === "guess") patch((t) => ({ ...t, guess: e }));
        else if (e.type === "prompt_recorded")
          patch((t) => ({ ...t, promptId: e.id, similar: e.similar }));
        else if (e.type === "done")
          patch((t) => ({
            ...t,
            opinion: e.opinion ?? null,
            cited: e.citations_in_prose,
            uncited: e.uncited_facts,
            unverified: e.attribution_unverified,
            status: "done",
            busy: false,
          }));
        else if (e.type === "error") patch((t) => ({ ...t, error: e.message, busy: false, status: "error" }));
      }, undefined, history);
      patch((t) => ({ ...t, busy: false }));
    } catch (err) {
      // Out of allowance is not an error state: the turn is dropped rather than rendered as a failed answer,
      // and the gate takes over the composer so no further prompt can be sent.
      if (err instanceof RateLimitedError) {
        setGate({ limit: err.limit || 10, retryAfter: err.retryAfter });
        setTurns((prev) => prev.filter((x) => x.id !== id));
      } else if (err instanceof TypeError) {
        // `fetch` rejects with a TypeError for a cross-origin response the browser refused to hand over. A
        // 429 without CORS headers looks exactly like this, so rather than render a scary "Failed to fetch"
        // we ask a free endpoint whether we are simply out of allowance, and gate if so.
        const gated = await promptStore.gateCheck();
        if (gated) {
          setGate(gated);
          setTurns((prev) => prev.filter((x) => x.id !== id));
        } else {
          patch((t) => ({ ...t, error: String(err), busy: false, status: "error" }));
        }
      } else {
        patch((t) => ({ ...t, error: String(err), busy: false, status: "error" }));
      }
    } finally {
      busyRef.current = false;
    }
  }

  const laHealth = (health?.laya ?? null) as null | { enabled?: boolean; loaded?: boolean; error?: string | null };

  /** Back to the empty state: clear the thread, the composer, and the drawer.
   *  Scroll position is reset too, otherwise returning home drops you at the bottom of the previous thread. */
  function goHome() {
    setTurns([]);
    turnsRef.current = [];
    setInput("");
    setNavOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  const empty = turns.length === 0;

  return (
    <div className="min-h-screen bg-paper">
      {/* masthead. Sticky so the panel toggle and the product name stay reachable on a long review,
          which matters most on a phone where the reading column is tall. z-30 keeps it under the
          drawer (z-50) and the composer (z-40) sits above it at the other end of the page. */}
      <header className="rule-b sticky top-0 z-30 bg-paper/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1180px] items-center gap-2 px-4 py-3 sm:gap-3 sm:px-6 sm:py-4">
          <button
            onClick={() => setNavOpen((v) => !v)}
            aria-label={navOpen ? "Hide context panel" : "Show context panel"}
            aria-expanded={navOpen}
            className="-ml-1 flex size-9 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-[var(--paper-sunk)] hover:text-ink sm:size-7"
          >
            <PanelLeft className="size-[15px]" strokeWidth={1.8} />
          </button>
          <button
            onClick={goHome}
            aria-label="pre-mortem home"
            className="font-display text-[17px] font-semibold tracking-tight text-ink transition-opacity hover:opacity-70"
          >
            pre&#8209;mortem
          </button>
          <span className="hidden text-[13px] text-ink-muted sm:inline">
            what your company already learned
          </span>
          <div className="ml-auto flex items-center gap-3">
            {showEvidence && (
              <span className="hidden text-[12px] text-ink-faint sm:inline">evidence open</span>
            )}
            {/* Visible before the limit bites, so running out is a known boundary rather than a surprise. */}
            {limitInfo?.enabled && limitInfo.requests_per_window ? (
              <span className="hidden font-mono text-[11.5px] text-ink-faint sm:inline">
                {Math.max(0, (limitInfo.requests_per_window ?? 0) - limitUsed)} of{" "}
                {limitInfo.requests_per_window} left
              </span>
            ) : null}
          </div>
        </div>
      </header>

      <Sidebar
        open={navOpen}
        onClose={() => setNavOpen(false)}
        settings={settings}
        onSetting={update}
        ledger={ledger}
        health={health}
        hideCalibration={latestNoPrecedent}
        unresolved={unresolved}
        onResolved={(id) => setUnresolved((prev) => prev.filter((x) => x.id !== id))}
        onDismissUnresolved={() => setUnresolved([])}
      />

      <main className="mx-auto max-w-[1180px] px-4 pb-40 sm:px-6 sm:pb-48">
        {empty && (
          <div className="grid gap-10 py-10 lg:grid-cols-[minmax(0,1fr)_360px] lg:gap-12 lg:py-14">
            <div className="measure">
              <h1 className="font-display text-[30px] font-normal leading-[1.15] tracking-tight text-ink sm:text-[40px]">
                Flag a decision before you make it.
              </h1>
              <p className="mt-5 text-[16px] leading-relaxed text-ink-soft">
                Describe what you are considering. It searches what this company has actually done before,
                names what went wrong, and cites every past decision by id.
              </p>
              <p className="mt-3 text-[16px] leading-relaxed text-ink-soft">
                When there is no precedent, it says so instead of guessing.
              </p>

              {/* Recording a decision that already happened, without reviewing it first. Without this the
                  only way to build the history is to phrase a past event as a future question, which is
                  both awkward and wrong: it is not a decision being considered. */}
              <div className="mt-8 border-t border-rule pt-6">
                <p className="text-[14px] text-ink-soft">
                  Already made a decision?
                </p>
                <p className="mt-1 text-[13px] leading-relaxed text-ink-muted">
                  Record it and future reviews can recall it by id.
                </p>
                {recordOpen ? (
                  <div className="mt-3">
                    <textarea
                      rows={2}
                      value={recordSeed}
                      onChange={(e) => setRecordSeed(e.target.value)}
                      placeholder="What did you decide? e.g. We gave Acme a 30 percent discount to close the renewal."
                      className="w-full resize-y rounded-md border border-[var(--rule-strong)] bg-paper-raised px-3 py-2 text-[14px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
                    />
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <button
                        onClick={() => {
                          setRecordOpen(false);
                          setRecordFor(recordSeed.trim());
                        }}
                        disabled={!recordSeed.trim()}
                        className="min-h-[36px] rounded-md bg-accent px-3.5 text-[13px] text-white transition-opacity hover:bg-accent-deep disabled:opacity-40"
                      >
                        Draft it
                      </button>
                      <button
                        onClick={() => { setRecordOpen(false); setRecordSeed(""); }}
                        className="min-h-[36px] rounded-md px-3 text-[13px] text-ink-muted transition-colors hover:bg-[var(--paper-sunk)] hover:text-ink"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => setRecordOpen(true)}
                    className="mt-3 inline-flex min-h-[38px] items-center gap-1.5 rounded-md border border-[var(--rule-strong)] px-3.5 text-[13px] text-ink transition-colors hover:bg-[var(--paper-sunk)]"
                  >
                    <Plus className="size-[14px]" strokeWidth={2.2} />
                    Add a decision
                  </button>
                )}
              </div>

              <div className="mt-9">
                <Label>Try one</Label>
                <div className="mt-3 divide-y divide-[var(--rule)] rule-t rule-b">
                  {presets.map((p) => (
                    <button
                      key={p.key}
                      onClick={() => ask(p.text)}
                      className="group flex w-full items-baseline gap-4 py-3.5 text-left transition-colors hover:bg-[var(--paper-sunk)]"
                    >
                      <span className="flex-1">
                        <span className="block text-[15px] text-ink group-hover:text-accent-deep">{p.label}</span>
                        <span className="mt-0.5 block text-[12.5px] text-ink-faint">{p.expect}</span>
                      </span>
                      <ArrowUp className="size-4 shrink-0 rotate-45 text-ink-faint transition-colors group-hover:text-accent" />
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* the apparatus, stated up front */}
            <aside className="lg:pt-3">
              <Label>How it works</Label>
              <ol className="mt-3 space-y-3 text-[13.5px] leading-relaxed text-ink-muted">
                <li>
                  <span className="text-ink-soft">Classified locally.</span> A small model reads the decision
                  and returns a calibrated area, reversibility, and whether value is being given away.
                </li>
                <li>
                  <span className="text-ink-soft">Remembered.</span> Hindsight recalls the company&apos;s own
                  past decisions, with how much evidence stands behind each.
                </li>
                <li>
                  <span className="text-ink-soft">Decided, not guessed.</span> The verdict comes from what
                  actually happened to those past decisions. No model chooses the risk level.
                </li>
                <li>
                  <span className="text-ink-soft">Written.</span> Only then does a model write the prose, and
                  every sentence carries a decision id.
                </li>
              </ol>
            </aside>
          </div>
        )}

        {turns.map((t) => (
          <article key={t.id} className="py-8 rule-b sm:py-11">
            {/* the question, set as a pull quote */}
            <h2 className="measure font-display text-[22px] font-normal leading-snug text-ink sm:text-[25px]">
              {t.question}
            </h2>

            {t.busy && t.mode !== "chat" && (
              <div className="mt-4 flex items-center gap-2.5 text-[13px] text-ink-muted">
                <span className="inline-block size-[7px] animate-pulse rounded-full bg-accent" />
                {t.status}…
              </div>
            )}

            {t.error && (
              <div className="measure mt-4 border-l-2 border-risk-high bg-[var(--risk-high-wash)] px-4 py-3 text-[13.5px] text-ink-soft">
                {t.error}
              </div>
            )}

            {t.risk && t.mode !== "chat" && (
              <div className="mt-5 flex flex-wrap items-baseline gap-x-5 gap-y-2">
                <RiskMark risk={t.risk} />
                {!t.noPrecedent && (
                  <span className="font-mono text-[13px] text-ink-faint">
                    confidence {t.confidence?.toFixed(2)}
                  </span>
                )}
                <span className="measure flex-1 text-[13.5px] text-ink-muted">{t.rules}</span>
              </div>
            )}

            {showEvidence && t.domain && !t.noPrecedent && t.mode !== "chat" && (
              <LayaNote laya={t.laya ?? null} domain={t.domain} dtype={t.dtype ?? ""} />
            )}

            {t.mode !== "chat" && <div className="mt-4"><Thinking text={t.thinking ?? ""} busy={t.busy} /></div>}

            {/* the review.
                Three shapes:
                  - no precedent: the refusal, then the guess at FULL WIDTH (a two-column grid left an empty
                    360px rail beside it, which read as broken)
                  - follow-up: compact prose only. Same memory and same citations, no repeated dossier
                  - opening question: the full dossier, prose left and the apparatus at the margin
            */}
            {t.mode === "chat" || t.mode === "query" ? (
              // Ordinary conversation: plain prose, no risk banner, no dossier, no citations. The whole
              // point is that it reads as a normal assistant reply, not as a reviewed decision.
              <div className="mt-5 max-w-[68ch]">
                <Thinking text={t.thinking ?? ""} busy={t.busy} />
                <p className="prose-editorial mt-2 text-[15px] leading-relaxed text-ink-soft">
                  {t.streamed || t.busy ? (
                    <>
                      {/* Through AnnotatedProse, not raw: id mentions in a follow-up must render as the same
                          pills, or a citation in the prose looks like plain text. */}
                      <AnnotatedProse text={t.streamed} precedents={t.precedents ?? []} />
                      {t.busy && <span className="caret" />}
                    </>
                  ) : (
                    "(no reply)"
                  )}
                </p>
              </div>
            ) : t.noPrecedent ? (
              <>
                <p className="measure prose-editorial mt-6 text-[15px] leading-relaxed text-ink-soft">
                  <AnnotatedProse text={t.streamed} precedents={t.precedents ?? []} />
                  {t.busy && <span className="caret" />}
                </p>
                {t.guess && (
                  <div className="fade-up mt-7 w-full">
                    <GuessPanel guess={t.guess} />
                  </div>
                )}
              </>
            ) : (
              (t.opinion?.headline || t.streamed) && (
                <div className="mt-6 grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_360px]">
                  <div className="measure prose-editorial">
                    {t.opinion?.headline ? (
                      <>
                        <p className="font-display !mb-4 text-[19px] leading-snug text-ink">
                          <AnnotatedProse text={t.opinion.headline} precedents={t.precedents ?? []} />
                        </p>
                        {t.opinion.why && (
                          <p className="text-[15px] leading-relaxed text-ink-soft">
                            <AnnotatedProse text={t.opinion.why} precedents={t.precedents ?? []} />
                          </p>
                        )}
                      </>
                    ) : (
                      <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink-soft">
                        <AnnotatedProse text={t.streamed} precedents={t.precedents ?? []} />
                        {t.busy && <span className="caret" />}
                      </p>
                    )}
                  </div>

                  {/* the difference: the one claim that is not a similarity search */}
                  <aside className="lg:pt-1">
                    {t.opinion?.differentiating_detail && (
                      <div className="fade-up border-l-2 border-accent bg-[var(--accent-wash)] px-4 py-3.5">
                        <Label className="text-accent-deep">The difference</Label>
                        <p className="mt-2 text-[13.5px] leading-relaxed text-ink-soft">
                          <AnnotatedProse
                            text={t.opinion.differentiating_detail}
                            precedents={t.precedents ?? []}
                          />
                        </p>
                      </div>
                    )}
                    {t.opinion?.suggested_guardrail && (
                      <div className="mt-5">
                        <Label>Make it safe</Label>
                        <p className="mt-2 text-[13.5px] leading-relaxed text-ink-soft">
                          <AnnotatedProse
                            text={t.opinion.suggested_guardrail}
                            precedents={t.precedents ?? []}
                          />
                        </p>
                      </div>
                    )}
                    {t.opinion?.open_questions && t.opinion.open_questions.length > 0 && (
                      <div className="mt-5">
                        <Label>Confirm first</Label>
                        <ul className="mt-2 space-y-2">
                          {t.opinion.open_questions.map((q, i) => (
                            <li key={i} className="flex gap-2.5 text-[13.5px] leading-relaxed text-ink-soft">
                              <span className="mt-[7px] size-1 shrink-0 rounded-full bg-ink-faint" />
                              <span>
                                <AnnotatedProse text={q} precedents={t.precedents ?? []} />
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </aside>
                </div>
              )
            )}

            {/* sources: always visible as pills, so every claim stays attributable at a glance.
                The full records are behind the pill click, or revealed wholesale with "show sources". */}
            {t.mode !== "chat" && t.precedents && t.precedents.length > 0 && (
              <SourceRow precedents={t.precedents} citedIds={t.cited ?? []} />
            )}

            {/* The commit gate, plus what this prompt resembles.
                "Add a decision" is offered only where the message proposes a decision to judge
                (`t.mode === "decision"`): a greeting or a history question is not a decision the company
                made, and offering to store it as one would fill the history with noise. */}
            {/* `!t.commitDismissed` is load-bearing: dismissal sets promptId to null, and `null !== undefined`
                is true, so the guard alone would never hide the panel. */}
            {t.promptId !== undefined && !t.commitDismissed && !t.followUp && !t.busy && t.mode === "decision" && (
              <CommitPrompt
                prompt={t.question}
                domain={t.domain}
                decisionType={t.dtype}
                risk={t.risk}
                similar={t.similar ?? []}
                committed={Boolean(t.committedDecisionId)}
                onAdd={() => setTurns((prev) => prev.map((x) => (x.id === t.id ? { ...x, adding: true } : x)))}
                onDismiss={() => setTurns((prev) => prev.map((x) => (x.id === t.id ? { ...x, promptId: null, commitDismissed: true } : x)))}
              />
            )}

            {/* The decision capture sheet. A portal-free fixed overlay, rendered per turn, so it is tied to
                the review it came from. */}
            {t.adding && (
              <AddDecision
                prompt={t.question}
                promptId={t.promptId}
                domain={t.domain}
                decisionType={t.dtype}
                risk={t.risk}
                headline={t.opinion?.headline ?? undefined}
                onClose={() => setTurns((prev) => prev.map((x) => (x.id === t.id ? { ...x, adding: false } : x)))}
                onAdded={(decisionId) =>
                  setTurns((prev) =>
                    prev.map((x) => (x.id === t.id ? { ...x, adding: false, addedDecisionId: decisionId } : x)))
                }
              />
            )}

            {t.addedDecisionId && (
              <p className="mt-4 border-l-2 border-risk-low bg-[var(--risk-low-wash)] px-4 py-3 text-[13px] text-ink-soft">
                Added to the history as <span className="font-mono text-[12px]">{t.addedDecisionId}</span>.
                Future reviews can recall and cite it.
              </p>
            )}

            {showEvidence && t.mode !== "chat" && (
              <section className="mt-8">
                {t.unverified && t.unverified.length > 0 && (
                  <p className="mb-3 text-[12.5px] text-risk-medium">
                    {t.unverified.join(", ")}: id unverified against the corpus, so the content is used but the
                    id is not quoted.
                  </p>
                )}

                {/* expanded records, in citation order */}
                <ul className="divide-y divide-[var(--rule)] rule-t rule-b">
                  {t.precedents?.map((p) => (
                    <Citation key={p.launch_id} p={p} />
                  ))}
                </ul>

                {t.declined && t.declined.length > 0 && (
                  <div className="mt-5">
                    <Label>{t.noPrecedent ? "Considered and declined" : "Also considered and declined"}</Label>
                    <ul className="mt-3 space-y-2.5">
                      {t.declined.map((d) => (
                        <li key={d.launch_id} className="text-[13px] text-ink-muted">
                          <DecisionId id={d.launch_id} />
                          {!t.noPrecedent && <> · evidence {d.proof_count}</>} — {d.reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            )}
          </article>
        ))}
        <div ref={endRef} />
      </main>

      {/* Recording a decision from the empty state uses the same sheet, with no review behind it. */}
      {recordFor !== null && (
        <AddDecision
          prompt={recordFor}
          promptId={null}
          onClose={() => { setRecordFor(null); setRecordSeed(""); }}
          onAdded={() => {
            setRecordFor(null);
            setRecordSeed("");
            // The new decision starts unresolved, so pull the queue forward for the sidebar.
            promptStore.unresolved(5).then((r) => setUnresolved(r.items ?? [])).catch(() => {});
          }}
        />
      )}

      {/* composer. When the allowance is gone the gate replaces it entirely, so there is no input left to
          type into and no submit button to press. */}
      {gate ? (
        <div className="fixed inset-x-0 bottom-0 border-t border-rule bg-paper/95 backdrop-blur">
          <div className="max-h-[70vh] overflow-y-auto">
            <ContactSales
              limit={gate.limit}
              retryAfterSeconds={gate.retryAfter}
              contactUrl={process.env.NEXT_PUBLIC_CONTACT_URL}
            />
          </div>
        </div>
      ) : (
      <div className="fixed inset-x-0 bottom-0 border-t border-rule bg-paper/95 backdrop-blur">
        <form
          className="mx-auto flex max-w-[1180px] items-end gap-2 px-4 py-3 sm:gap-3 sm:px-6 sm:py-4"
          onSubmit={(e) => {
            e.preventDefault();
            ask(input);
          }}
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                ask(input);
              }
            }}
            placeholder="Describe a decision you are considering…"
            // rows=2, not 1: the placeholder wraps to two lines in a 304px field at 390px width, and with a
            // single row the box was 48px tall against content that needed 72px, so the second line was
            // clipped AND `overflow-y: auto` drew a stray scrollbar inside the field.
            rows={2}
            // `min-w-0` is load-bearing: a flex item's automatic minimum size is its content width, and a
            // textarea's is its `cols` default, so without this it refused to shrink and pushed the whole
            // page 138px wider than a 390px viewport.
            className="max-h-40 min-h-[46px] min-w-0 flex-1 resize-none rounded-md border border-[var(--rule-strong)] bg-paper-raised px-3.5 py-3 text-[15px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
          />
          <button
            type="submit"
            disabled={!input.trim()}
            aria-label="Flag this decision"
            className="flex size-[46px] shrink-0 items-center justify-center rounded-md bg-accent text-white transition-opacity hover:bg-accent-deep disabled:opacity-35"
          >
            <ArrowUp className="size-[18px]" strokeWidth={2.2} />
          </button>
        </form>
      </div>
      )}
    </div>
  );
}
