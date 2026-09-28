"use client";
import { Activity, BookOpen, Check, ChevronLeft, SlidersHorizontal } from "lucide-react";
import type { Health, Ledger } from "@/lib/api";
import type { Density, Settings } from "@/lib/settings";
import { DecisionId, Label } from "@/components/editorial";
import { cn } from "@/lib/utils";
import { ThemeChoice } from "@/components/theme-toggle";

/** A labelled on/off switch, styled to the brand rather than as a generic checkbox. */
function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="group flex w-full items-start gap-3 py-2 text-left"
    >
      <span
        className={cn(
          "mt-[3px] flex h-[16px] w-[28px] shrink-0 items-center rounded-full border px-[2px] transition-colors",
          checked ? "border-accent bg-accent" : "border-[var(--rule-strong)] bg-[var(--paper-sunk)]",
        )}
      >
        <span
          className={cn(
            "block size-[10px] rounded-full bg-paper-raised transition-transform",
            checked && "translate-x-[12px] bg-white",
          )}
        />
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] text-ink-soft group-hover:text-ink">{label}</span>
        {hint && <span className="mt-0.5 block text-[11.5px] leading-relaxed text-ink-faint">{hint}</span>}
      </span>
    </button>
  );
}

/**
 * The context drawer.
 *
 * Layout notes, because the previous version was spaced wrong: the drawer is `fixed` so it never competes
 * with the reading column for grid space, the column keeps its own independent measure, and the panel
 * carries its own padding. Previously the wrapper had px-6, the main column had an unconditional pl-6, and
 * the closed drawer still drew a 1px right border, which double-padded the content and left a stray rule.
 */
export function Sidebar({
  open,
  onClose,
  settings,
  onSetting,
  ledger,
  health,
  hideCalibration,
}: {
  open: boolean;
  onClose: () => void;
  settings: Settings;
  onSetting: <K extends keyof Settings>(k: K, v: Settings[K]) => void;
  ledger: Ledger | null;
  health: Health | null;
  /** Hidden on a no-precedent answer: there is no calibration to point at, so showing counts would imply
   *  a conclusion the answer just declined to reach. */
  hideCalibration?: boolean;
}) {
  const la = (health?.laya ?? null) as null | { enabled?: boolean; loaded?: boolean } | undefined;

  return (
    <>
      {/* click-away shield: only present when open, so it cannot swallow clicks on the reading column */}
      {open && (
        <div
          onClick={onClose}
          aria-hidden="true"
          className="fixed inset-0 z-40 bg-black/25 backdrop-blur-[1px] lg:bg-black/0 lg:backdrop-blur-0"
        />
      )}

      <aside
        aria-hidden={!open}
        className={cn(
          // Full width on a phone (a 292px drawer on a 390px screen leaves an unreadable 98px sliver of
          // body text, which reads as a rendering bug rather than as a drawer), 320px from `sm` up.
          "fixed inset-y-0 left-0 z-50 flex w-full flex-col border-r border-rule bg-paper sm:w-[320px]",
          "transition-transform duration-200 ease-out",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        {/* header */}
        <div className="flex shrink-0 items-center gap-2 border-b border-rule px-5 py-4">
          <SlidersHorizontal className="size-[14px] text-ink-faint" strokeWidth={1.8} />
          <Label>Settings &amp; context</Label>
          <button
            onClick={onClose}
            aria-label="Close panel"
            className="ml-auto flex size-9 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-[var(--paper-sunk)] hover:text-ink"
          >
            <ChevronLeft className="size-[15px]" strokeWidth={1.8} />
          </button>
        </div>

        {/* one scroll region, with consistent rhythm via space-y on the sections. The bottom padding is
            safe-area aware: flush to the edge, the last calibration line was clipped at the viewport bottom
            and the closing rows sat under the phone's home indicator. */}
        <div
          className="min-h-0 flex-1 overflow-y-auto px-5 py-5"
          style={{ paddingBottom: "max(20px, env(safe-area-inset-bottom))" }}
        >
          <div className="space-y-7">
            {/* ------------------------------------------------ appearance */}
            <section>
              <Label>Appearance</Label>
              <ThemeChoice />
            </section>

            {/* ------------------------------------------------ settings */}
            <section>
              <Label>Display</Label>
              <div className="mt-1 divide-y divide-[var(--rule)]">
                <Toggle
                  label="Open evidence by default"
                  hint="show the full decision records instead of just the source pills"
                  checked={settings.sourcesOpen}
                  onChange={(v) => onSetting("sourcesOpen", v)}
                />
                <Toggle
                  label="Show engine detail"
                  hint="which component produced the verdict, and the model call count"
                  checked={settings.showEngine}
                  onChange={(v) => onSetting("showEngine", v)}
                />
              </div>

              <div className="mt-4">
                <div className="text-[13px] text-ink-soft">Citation density</div>
                <div className="mt-2 inline-flex rounded-md border border-[var(--rule-strong)] p-[2px]">
                  {(["comfortable", "compact"] as Density[]).map((d) => (
                    <button
                      key={d}
                      onClick={() => onSetting("density", d)}
                      className={cn(
                        // 40px minimum height: these were 27px, under the 44px touch guideline and easy to
                        // miss on a phone.
                        "min-h-[40px] rounded-[5px] px-4 text-[12.5px] capitalize transition-colors",
                        settings.density === d
                          ? "bg-[var(--paper-sunk)] text-ink"
                          : "text-ink-muted hover:text-ink",
                      )}
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </div>
            </section>

            {/* ------------------------------------------------ status */}
            {health && (
              <section>
                <Label>Status</Label>
                <ul className="mt-2.5 space-y-2">
                  <li className="flex items-center gap-2 text-[12.5px]">
                    <span
                      className={cn(
                        "flex size-[15px] shrink-0 items-center justify-center rounded-full border",
                        la?.loaded
                          ? "border-risk-low text-risk-low"
                          : "border-[var(--rule-strong)] text-ink-faint",
                      )}
                      aria-hidden="true"
                    >
                      {la?.loaded && <Check className="size-[10px]" strokeWidth={3} />}
                    </span>
                    <span className="text-ink-soft">
                      local classifier {la?.loaded ? "ready" : la?.enabled ? "loading" : "off"}
                    </span>
                  </li>
                  <li className="flex items-center gap-2 text-[12.5px]">
                    <span
                      className={cn(
                        "flex size-[15px] shrink-0 items-center justify-center rounded-full border",
                        health.ok
                          ? "border-risk-low text-risk-low"
                          : "border-risk-high text-risk-high",
                      )}
                      aria-hidden="true"
                    >
                      {health.ok && <Check className="size-[10px]" strokeWidth={3} />}
                    </span>
                    <span className="text-ink-soft">
                      memory {health.ok ? "connected" : "degraded"}
                    </span>
                  </li>
                </ul>
              </section>
            )}

            {/* ------------------------------------------------ ledger */}
            {ledger && !hideCalibration && (
              <section>
                <Label>Calibration</Label>
                <p className="mt-2 text-[12.5px] leading-relaxed text-ink-muted">
                  Decisions where the reviewer raised a warning and the company went ahead anyway. Where that
                  pattern repeats, the reviewer leads with it.
                </p>
                <dl className="mt-3 space-y-2">
                  {[
                    ["warnings raised", String(ledger.flags), "text-ink-soft"],
                    ["ignored anyway", String(ledger.ignored), "text-ink-soft"],
                    ["of those, cost something", String(ledger.costed), "text-risk-high"],
                  ].map(([k, v, tone]) => (
                    <div key={k} className="flex items-baseline justify-between gap-3">
                      <dt className="text-[12px] text-ink-faint">{k}</dt>
                      <dd className={cn("font-mono text-[13px]", tone)}>{v}</dd>
                    </div>
                  ))}
                </dl>

                {ledger.promoted_classes.length > 0 && (
                  <>
                    <Label className="mt-4">Now leads with</Label>
                    <ul className="mt-2 space-y-1">
                      {ledger.promoted_classes.map((c) => (
                        <li key={c} className="font-mono text-[11.5px] text-ink-soft">
                          {c}
                        </li>
                      ))}
                    </ul>
                  </>
                )}

                {ledger.rows?.length > 0 && (
                  <details className="mt-4">
                    <summary className="cursor-pointer text-[12px] text-ink-faint hover:text-ink-muted">
                      the {ledger.rows.length} {ledger.rows.length === 1 ? "decision" : "decisions"}
                    </summary>
                    <ul className="mt-3 space-y-3">
                      {ledger.rows.map((r) => (
                        <li key={r.decision_id} className="text-[12.5px] text-ink-muted">
                          <DecisionId id={r.decision_id} className="text-[11.5px]" />
                          {r.costed && <span className="ml-1.5 text-risk-high">cost something</span>}
                          <p className="mt-0.5 leading-relaxed">{r.text.slice(0, 140)}</p>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </section>
            )}

            {/* ------------------------------------------------ engine */}
            {settings.showEngine && health && (
              <section className="fade-up">
                <Label>Engine</Label>
                <ul className="mt-2.5 space-y-2 text-[12px] text-ink-muted">
                  <li className="flex items-start gap-2">
                    <Activity className="mt-[2px] size-[12px] shrink-0 text-ink-faint" strokeWidth={1.8} />
                    <span>
                      <span className="text-ink-soft">verdict</span> — deterministic ranker, no model opinion
                    </span>
                  </li>
                  <li className="flex items-start gap-2">
                    <Activity className="mt-[2px] size-[12px] shrink-0 text-ink-faint" strokeWidth={1.8} />
                    <span>
                      <span className="text-ink-soft">classifier</span> —{" "}
                      {la?.loaded ? "local model, loaded" : la?.enabled ? "local model, loading" : "off"}
                    </span>
                  </li>
                  <li className="flex items-start gap-2">
                    <BookOpen className="mt-[2px] size-[12px] shrink-0 text-ink-faint" strokeWidth={1.8} />
                    <span>
                      <span className="text-ink-soft">memory</span> — Hindsight,{" "}
                      {health.ok ? "both banks readable" : "degraded"}
                    </span>
                  </li>
                </ul>
              </section>
            )}

            {/* ------------------------------------------------ about */}
            <section>
              <Label>About</Label>
              <p className="mt-2 text-[12.5px] leading-relaxed text-ink-muted">
                Every claim in a review carries the id of a real past decision. When the company has no
                precedent, the answer says so and any guess is labelled separately.
              </p>
              <p className="mt-2 text-[11.5px] leading-relaxed text-ink-faint">
                Read-only. This tool does not decide, file, or approve anything.
              </p>
            </section>
          </div>
        </div>
      </aside>
    </>
  );
}
