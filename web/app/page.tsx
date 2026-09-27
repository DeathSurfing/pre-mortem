"use client";
import { useEffect, useState } from "react";
import { api, type Assessment, type Health, type Ledger, type Metrics, type PresetInfo } from "@/lib/api";

/* ---------- small presentational pieces ---------- */

function Trend({ trend }: { trend: string }) {
  return <span className={`trend ${trend}`}>{trend}</span>;
}

function Outcome({ outcome, isMirror }: { outcome: string | null; isMirror: boolean }) {
  if (isMirror) return <span className="badge mirror">near-identical clean mirror</span>;
  if (!outcome) return null;
  return <span className={`badge ${outcome}`}>{outcome}</span>;
}

function PrecedentCard({ p, top }: { p: Assessment["precedents"][number]; top: boolean }) {
  return (
    <div className={`prec${top ? " top" : ""}`}>
      <div className="head">
        <span className="lid">{p.launch_id}</span>
        <span className="dim">{p.date}</span>
        <span className="badge proof" title="Hindsight proof count for this memory">
          proof {p.proof_count}
        </span>
        <Trend trend={p.trend} />
        <Outcome outcome={p.outcome} isMirror={p.is_mirror} />
        <span className="dim">{p.service} · {p.change_class}</span>
        <span className="dim" style={{ marginLeft: "auto" }} title="rank score, shown so the ranking is not a black box">
          score {p.score.total}
        </span>
      </div>
      {p.text && <div className="txt">{p.text}</div>}
      {p.source_chunk && (
        <details>
          <summary>source chunk used for retrieval</summary>
          <div className="chunk">{p.source_chunk}</div>
        </details>
      )}
    </div>
  );
}

function Flip({ flip, precedents }: { flip: Assessment["flip"]; precedents: Assessment["precedents"] }) {
  if (!flip) return null;
  const cited = precedents.find((p) => p.launch_id === flip.precedent_launch_id);
  return (
    <div className="flip">
      <div className="h">the difference · not a similarity match</div>
      <p className="detail">{flip.differentiating_detail}</p>
      {flip.why_it_matters && <p className="why">{flip.why_it_matters}</p>}
      {flip.cited_fix && (
        <div className="fix">
          <b>fix that resolved it:</b> {flip.cited_fix}
        </div>
      )}
      <div className="cite">
        cited precedent: <span className="mono">{flip.precedent_launch_id}</span>
        {cited ? ` · ${cited.date} · proof ${cited.proof_count}` : " (not in the recalled set — flagged)"}
      </div>
    </div>
  );
}

/* ---------- the screen ---------- */

export default function Page() {
  const [health, setHealth] = useState<Health | null>(null);
  const [presets, setPresets] = useState<PresetInfo[]>([]);
  const [sel, setSel] = useState("A");
  const [memory, setMemory] = useState(true);
  const [engine, setEngine] = useState<"recall" | "reflect">("recall");
  const [out, setOut] = useState<Assessment | null>(null);
  const [off, setOff] = useState<Assessment | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setErr(String(e)));
    api.presets().then(setPresets).catch(() => {});
    api.ledger().then(setLedger).catch(() => {});
    api.metrics().then(setMetrics).catch(() => {});
  }, []);

  async function run(withMemory: boolean, eng: "recall" | "reflect" = engine) {
    setBusy(true);
    setErr("");
    try {
      const r = await api.assess(sel, withMemory, eng);
      if (withMemory) setOut(r);
      else setOff(r);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  const preset = presets.find((p) => p.key === sel);

  return (
    <div className="shell">
      <div className="topbar">
        <h1>pre-mortem</h1>
        <span className="tag">your deploy history, argued back at you before you ship</span>
        <span className="spacer" />
        <span className="dim">
          {health?.features?.api_version ? `hindsight ${health.features.api_version}` : ""}
          {health?.models ? ` · ${health.models.llm}` : ""}
          {health?.bank ? ` · ${health.documents?.length ?? 0} docs` : ""}
        </span>
      </div>

      {(err || (health && !health.ok)) && (
        <div className="warn" style={{ marginBottom: 14 }}>
          {err || `backend not ready: ${health?.error || (health?.problems || []).join("; ")}`}
        </div>
      )}

      <div className="grid">
        {/* ---------------- left: the pending change ---------------- */}
        <div>
          <div className="card">
            <h2>pending change</h2>
            {presets.map((p) => (
              <button
                key={p.key}
                className={`preset${sel === p.key ? " sel" : ""}`}
                onClick={() => {
                  setSel(p.key);
                  setOut(null);
                  setOff(null);
                }}
              >
                <span className="k">{p.key}</span>
                <span className="lbl">
                  {p.service} · {p.change_class}
                </span>
                <span className="svc">{p.change}</span>
              </button>
            ))}
            {preset && (
              <>
                <h3 style={{ marginTop: 14 }}>diff</h3>
                <div className="diff">{preset.diff}</div>
              </>
            )}
          </div>

          <div className="card">
            <h2>memory</h2>
            <div className="row" style={{ marginBottom: 10 }}>
              <button className={memory ? "on" : ""} onClick={() => setMemory(true)}>
                on
              </button>
              <button className={!memory ? "on" : ""} onClick={() => setMemory(false)}>
                off
              </button>
            </div>
            <div className="dim" style={{ marginBottom: 10 }}>
              {memory
                ? "recall + rank, cited. recall uses no LLM."
                : "no history at all: the same question with an empty memory."}
            </div>
            <div className="row">
              <button className={engine === "recall" ? "on" : ""} onClick={() => setEngine("recall")}>
                recall engine
              </button>
              <button className={engine === "reflect" ? "on" : ""} onClick={() => setEngine("reflect")}>
                reflect engine
              </button>
            </div>
            <div className="dim" style={{ marginTop: 8 }}>
              reflect costs tokens (Hindsight answers it itself). recall is retrieval only.
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="primary" disabled={busy} onClick={() => run(memory, engine)}>
                {busy ? <span className="spin" /> : null} assess
              </button>
              <button className="ghost" disabled={busy} onClick={() => run(false, "recall")}>
                run memory=off
              </button>
            </div>
          </div>

          {ledger && (
            <div className="card">
              <h2>ignored-warning ledger</h2>
              <div className="kv">
                <span className="k">flags raised</span>
                <span className="v">{ledger.flags}</span>
                <span className="k">ignored</span>
                <span className="v">{ledger.ignored}</span>
                <span className="k">cost an incident</span>
                <span className="v">{ledger.costed}</span>
              </div>
              {ledger.promoted_classes.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div className="dim">now leads with:</div>
                  {ledger.promoted_classes.map((c) => (
                    <div key={c} className="mono" style={{ color: "var(--accent)", fontSize: 12.5 }}>
                      {c}
                    </div>
                  ))}
                </div>
              )}
              <details style={{ marginTop: 10 }}>
                <summary className="dim">every flag</summary>
                {ledger.rows.map((r, i) => (
                  <div key={i} className="declined" style={{ marginTop: 8 }}>
                    <div className="mono" style={{ fontSize: 12 }}>
                      {r.launch_id} · {r.ignored ? "ignored" : "actioned"}
                      {r.costed ? " · cost an incident" : ""}
                    </div>
                    <div className="r">{r.text}</div>
                  </div>
                ))}
              </details>
            </div>
          )}

          {metrics && (
            <div className="card">
              <h2>replay, no lookahead</h2>
              <div className="kv">
                <span className="k">materialised launches</span>
                <span className="v">{metrics.totals.launches}</span>
                <span className="k">precedent derivable</span>
                <span className="v">{metrics.totals.derivable}</span>
                <span className="k">agent actually found</span>
                <span className="v">{metrics.totals.found_precedent}</span>
                <span className="k">missed</span>
                <span className="v">{metrics.totals.gap}</span>
              </div>
              <div className="bars">
                {metrics.epochs.map((e) => (
                  <div
                    key={e.epoch}
                    className="b"
                    style={{ height: `${Math.max(4, (e.flagged_high / metrics.epochs[0].launches) * 100)}%` }}
                  >
                    <span>e{e.epoch}</span>
                  </div>
                ))}
              </div>
              <div className="dim" style={{ marginTop: 22 }}>
                bars = launches flagged high risk per 5-launch epoch. {metrics.method}
              </div>
            </div>
          )}
        </div>

        {/* ---------------- right: the answer ---------------- */}
        <div>
          {off && !out && (
            <div className="card">
              <h2>memory=off baseline</h2>
              <div className="txt" style={{ whiteSpace: "pre-wrap", color: "#c9d5e1" }}>
                {off.baseline || "(no output)"}
              </div>
              <div className="dim" style={{ marginTop: 10 }}>
                nothing here is checkable: no launch id, no proof count, no way to know if it happened before.
              </div>
            </div>
          )}

          {out && (
            <>
              <div className={`banner risk-${out.risk}`}>
                <div>
                  <div className="risk">{out.risk === "unknown" ? "no precedent" : `${out.risk} risk`}</div>
                  <div className="dim">{out.verdict_rules}</div>
                </div>
                <div className="conf">
                  <b>{out.no_precedent ? "—" : out.confidence.toFixed(2)}</b>
                  <span className="dim">confidence from proof counts</span>
                </div>
              </div>

              <div style={{ height: 14 }} />

              {out.no_precedent && (
                <div className="card">
                  <h2>refusing to stretch an analogy</h2>
                  <div className="txt">{out.no_precedent_message}</div>
                  {out.declined.length > 0 && (
                    <>
                      <h3 style={{ marginTop: 14 }}>considered and declined</h3>
                      {out.declined.map((d, i) => (
                        <div key={i} className="declined">
                          <div className="mono" style={{ fontSize: 12.5 }}>
                            {d.launch_id ?? "(unattributed memory)"} · proof {d.proof_count}
                          </div>
                          <div className="r">{d.reason}</div>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}

              {out.flip && <Flip flip={out.flip} precedents={out.precedents} />}

              {out.reflect?.text && (
                <div className="card">
                  <h2>hindsight reflect answered it itself</h2>
                  <div className="txt" style={{ whiteSpace: "pre-wrap", color: "#c9d5e1" }}>
                    {out.reflect.text}
                  </div>
                  {out.reflect.based_on && out.reflect.based_on.length > 0 && (
                    <details style={{ marginTop: 10 }}>
                      <summary className="dim">based on {out.reflect.based_on.length} memories</summary>
                      {out.reflect.based_on.map((m, i) => (
                        <div key={i} className="chunk">
                          {m.text}
                        </div>
                      ))}
                    </details>
                  )}
                </div>
              )}

              <div className="card">
                <h2>
                  precedents {out.precedents.length > 0 ? `(${out.precedents.length}, ranked)` : "(none)"}
                </h2>
                {out.precedents.map((p, i) => (
                  <PrecedentCard key={p.launch_id || i} p={p} top={i === 0} />
                ))}
                {out.precedents.length === 0 && (
                  <div className="dim">nothing cleared the proof threshold for this service and change class.</div>
                )}
                {out.precedents.some((p) => p.is_mirror) && (
                  <div className="dim" style={{ marginTop: 6 }}>
                    a clean mirror is present: the near-identical launch that did <b>not</b> break. That contrast is
                    what the flip detail is extracted from.
                  </div>
                )}
              </div>

              {out.declined.length > 0 && !out.no_precedent && (
                <div className="card">
                  <h2>also considered, declined</h2>
                  {out.declined.map((d, i) => (
                    <div key={i} className="declined">
                      <div className="mono" style={{ fontSize: 12.5 }}>
                        {d.launch_id ?? "(unattributed)"} · {d.service} · {d.change_class}
                      </div>
                      <div className="r">{d.reason}</div>
                    </div>
                  ))}
                </div>
              )}

              <div className="card">
                <h2>how this answer was produced</h2>
                <div className="kv">
                  <span className="k">verdict by</span>
                  <span className="v">{out.engine.ranker} ranker (no model)</span>
                  <span className="k">engine</span>
                  <span className="v">{out.engine.engine || out.engine.ranker}</span>
                  <span className="k">llm calls</span>
                  <span className="v">
                    {out.engine.llm_calls} → wrote the flip sentence only
                  </span>
                  <span className="k">model</span>
                  <span className="v">{out.engine.model_used || out.engine.llm}</span>
                  <span className="k">facts used</span>
                  <span className="v">{out.facts_used.join(", ") || "none"}</span>
                  <span className="k">errors</span>
                  <span className="v">{out.engine.llm_error || "none"}</span>
                  <span className="k">ledger</span>
                  <span className="v">
                    {out.ledger_promoted.length ? out.ledger_promoted.join(", ") : "no promoted classes yet"}
                  </span>
                </div>
                {out.engine.citation_warning && (
                  <div className="warn" style={{ marginTop: 10 }}>
                    {out.engine.citation_warning}
                  </div>
                )}
                <div className="row" style={{ marginTop: 12 }}>
                  <button
                    className="ghost"
                    onClick={async () => {
                      setShowPreview((v) => !v);
                      if (!preview) setPreview(await api.promptPreview("retain").catch((e) => ({ error: String(e) })));
                    }}
                  >
                    {showPreview ? "hide" : "show"} the assembled prompt
                  </button>
                </div>
                {showPreview && preview && (
                  <pre className="raw">{JSON.stringify(preview, null, 1)}</pre>
                )}
              </div>
            </>
          )}

          {!out && !off && (
            <div className="card">
              <h2>start here</h2>
              <div className="dim">
                Pick a pending change on the left, then assess it twice: once with memory off and once with memory on.
                The difference is the product.
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
