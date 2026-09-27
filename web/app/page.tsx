"use client";
import { useEffect, useRef, useState } from "react";
import {
  api,
  streamRedflag,
  type Declined,
  type Ledger,
  type LayaSignals,
  type Opinion,
  type Precedent,
  type PromptPreset,
} from "@/lib/api";

/* ---------------------------------------------------------------- pieces */

function RiskBanner({ risk, confidence, noPrecedent, rules }: {
  risk: string; confidence: number; noPrecedent: boolean; rules: string;
}) {
  const label = noPrecedent ? "no precedent" : `${risk} risk`;
  return (
    <div className={`banner risk-${risk}`}>
      <div>
        <div className="risk">{label}</div>
        <div className="dim">{rules}</div>
      </div>
      <div className="conf">
        <b>{noPrecedent ? "—" : confidence.toFixed(2)}</b>
        <span className="dim">confidence from evidence</span>
      </div>
    </div>
  );
}

function LayaPanel({ laya, domain, dtype }: { laya: LayaSignals | null; domain: string; dtype: string }) {
  if (!laya) return null;
  const pct = (v: number | null) => (v === null ? "—" : `${(v * 100).toFixed(0)}%`);
  return (
    <div className="laya">
      <div className="laya-head">
        <span className="badge">classified locally by Laya</span>
        <span className="mono">{domain} / {dtype}</span>
      </div>
      <div className="laya-grid">
        <div>
          <span className="dim">domain certainty</span>
          <b>{pct(laya.domain_confidence)}</b>
        </div>
        <div>
          <span className="dim">reversibility</span>
          <b>{laya.reversibility_label ?? "—"}</b>
        </div>
        <div>
          <span className="dim">value given away</span>
          <b>{pct(laya.gives_value_without_commitment)}</b>
        </div>
        <div>
          <span className="dim">blast radius</span>
          <b>{pct(laya.is_high_blast_radius)}</b>
        </div>
      </div>
    </div>
  );
}

function PrecedentCard({ p, top }: { p: Precedent; top: boolean }) {
  return (
    <div className={`prec${top ? " top" : ""}${p.attribution_ok ? "" : " suspect"}`}>
      <div className="head">
        <span className="lid">{p.launch_id}</span>
        <span className="dim">{p.date}</span>
        <span className="badge proof" title="how much evidence stands behind this">
          evidence {p.proof_count}
        </span>
        {p.is_mirror ? (
          <span className="badge mirror">near-identical, went fine</span>
        ) : p.outcome ? (
          <span className={`badge ${p.outcome}`}>{p.outcome}</span>
        ) : (
          <span className="badge">outcome not recorded</span>
        )}
        {!p.attribution_ok && (
          <span className="badge suspect" title="this record's id could not be verified against the corpus">
            id unverified
          </span>
        )}
        <span className="dim" style={{ marginLeft: "auto" }}>
          {p.domain} · {p.decision_type}
        </span>
      </div>
      {p.text && <div className="txt">{p.text}</div>}
    </div>
  );
}

/* ---------------------------------------------------------------- the chat */

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
  error?: string;
  busy: boolean;
};

export default function Page() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [presets, setPresets] = useState<PromptPreset[]>([]);
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [showEvidence, setShowEvidence] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    api.prompts().then(setPresets).catch(() => {});
    api.ledger().then(setLedger).catch(() => {});
    api.health().then(setHealth).catch(() => {});
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  async function ask(text: string) {
    const question = text.trim();
    if (!question || busyRef.current) return;
    busyRef.current = true;
    setInput("");
    const id = `${Date.now()}`;
    const patch = (fn: (t: Turn) => Turn) =>
      setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)));

    setTurns((prev) => [
      ...prev,
      { id, question, status: "connecting", streamed: "", busy: true },
    ]);

    try {
      await streamRedflag(question, (e) => {
        if (e.type === "status") patch((t) => ({ ...t, status: e.message }));
        else if (e.type === "classify")
          patch((t) => ({ ...t, domain: e.domain, dtype: e.decision_type, laya: e.laya, status: "recalling" }));
        else if (e.type === "verdict")
          patch((t) => ({ ...t, risk: e.risk, confidence: e.confidence, noPrecedent: e.no_precedent, rules: e.rules, status: "writing" }));
        else if (e.type === "precedents")
          patch((t) => ({ ...t, precedents: e.precedents, declined: e.declined }));
        else if (e.type === "delta") patch((t) => ({ ...t, streamed: t.streamed + e.text }));
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
      });
      patch((t) => ({ ...t, busy: false }));
    } catch (err) {
      patch((t) => ({ ...t, error: String(err), busy: false, status: "error" }));
    } finally {
      busyRef.current = false;
    }
  }

  const laHealth = (health?.laya ?? null) as null | {
    enabled?: boolean;
    loaded?: boolean;
    error?: string | null;
  };

  return (
    <div className="shell chat-shell">
      <div className="topbar">
        <h1>pre-mortem</h1>
        <span className="tag">flag a decision before you make it, from what your company already learned</span>
        <span className="spacer" />
        {laHealth && (
          <span className="dim" title={String(laHealth.error || "Laya classifies each decision locally, offline")}>
            laya {laHealth.loaded ? "ready" : laHealth.enabled ? "loading" : "off"}
          </span>
        )}
        <button className="ghost" onClick={() => setShowEvidence((v) => !v)}>
          {showEvidence ? "hide" : "show"} evidence
        </button>
      </div>

      {ledger && ledger.promoted_classes.length > 0 && (
        <div className="ledgerbar">
          <span className="dim">this company has been burned before on:</span>
          {ledger.promoted_classes.map((c) => (
            <span key={c} className="badge promoted">{c}</span>
          ))}
          <span className="dim">
            {ledger.ignored} of {ledger.flags} past warnings were ignored, {ledger.costed} of those cost something
          </span>
        </div>
      )}

      <div className="thread">
        {turns.length === 0 && (
          <div className="empty">
            <h2>Ask about a decision you are considering</h2>
            <p className="dim">
              It searches what this company has actually done before and flags what went wrong, citing each
              past decision by id. No precedent means it says so instead of inventing one.
            </p>
            <div className="presets">
              {presets.map((p) => (
                <button key={p.key} className="preset-chip" onClick={() => ask(p.text)}>
                  <b>{p.label}</b>
                  <span className="dim">{p.expect}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((t) => (
          <div key={t.id} className="turn">
            <div className="q">{t.question}</div>

            {t.status !== "done" && t.status !== "error" && (
              <div className="stage">
                <span className="spin" />
                <span className="dim">{t.status}…</span>
              </div>
            )}

            {t.error && <div className="warn">{t.error}</div>}

            {t.risk && (
              <RiskBanner risk={t.risk} confidence={t.confidence ?? 0} noPrecedent={!!t.noPrecedent} rules={t.rules ?? ""} />
            )}

            {showEvidence && t.laya !== undefined && t.domain && (
              <LayaPanel laya={t.laya ?? null} domain={t.domain} dtype={t.dtype ?? ""} />
            )}

            {t.opinion?.headline && (
              <div className="answer">
                <p className="headline">{t.opinion.headline}</p>
                {t.opinion.why && <p className="why">{t.opinion.why}</p>}
                {t.opinion.differentiating_detail && (
                  <div className="flip">
                    <div className="h">the difference · not a similarity match</div>
                    <p className="detail">{t.opinion.differentiating_detail}</p>
                  </div>
                )}
                {t.opinion.suggested_guardrail && (
                  <div className="guard">
                    <b>make it safe:</b> {t.opinion.suggested_guardrail}
                  </div>
                )}
                {t.opinion.open_questions?.length > 0 && (
                  <div className="qs">
                    <div className="dim">confirm first</div>
                    <ul>
                      {t.opinion.open_questions.map((q, i) => (
                        <li key={i}>{q}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* while streaming, show the raw text as it arrives */}
            {t.busy && t.streamed && (
              <div className="answer streaming">
                <pre>{t.streamed}</pre>
                <span className="caret" />
              </div>
            )}

            {!t.busy && !t.opinion?.headline && t.streamed && (
              <div className="answer">
                <pre>{t.streamed}</pre>
              </div>
            )}

            {showEvidence && t.precedents && t.precedents.length > 0 && (
              <div className="evidence">
                <div className="ev-head">
                  <span className="dim">
                    {t.precedents.length} precedents
                    {t.cited?.length ? ` · ${t.cited.length} cited in the answer` : ""}
                    {t.uncited?.length ? ` · ${t.uncited.length} uncited` : ""}
                  </span>
                </div>
                {t.precedents.map((p, i) => (
                  <PrecedentCard key={p.launch_id || i} p={p} top={i === 0} />
                ))}
                {t.unverified && t.unverified.length > 0 && (
                  <div className="warn" style={{ marginTop: 8 }}>
                    {t.unverified.join(", ")}: the id could not be verified against the corpus, so the
                    content is used but the id is not quoted.
                  </div>
                )}
                {t.declined && t.declined.length > 0 && (
                  <details>
                    <summary className="dim">also considered, declined ({t.declined.length})</summary>
                    {t.declined.map((d) => (
                      <div key={d.launch_id} className="declined">
                        <div className="mono" style={{ fontSize: 12 }}>
                          {d.launch_id} · evidence {d.proof_count}
                        </div>
                        <div className="r">{d.reason}</div>
                      </div>
                    ))}
                  </details>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form
        className="composer"
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
          placeholder="Describe a decision you are considering…  (Enter to send, Shift+Enter for a new line)"
          rows={2}
        />
        <button className="primary" type="submit" disabled={!input.trim()}>
          flag it
        </button>
      </form>
    </div>
  );
}
