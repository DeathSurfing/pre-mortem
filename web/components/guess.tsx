"use client";
import { FlaskConical } from "lucide-react";
import type { GuessBlock } from "@/lib/api";
import { Label } from "@/components/editorial";

const CONF: Record<string, { label: string; className: string }> = {
  LOW: { label: "low confidence", className: "text-risk-medium" },
  MEDIUM: { label: "medium confidence", className: "text-ink-muted" },
  HIGH: { label: "high confidence", className: "text-ink-muted" },
};

/**
 * The no-precedent guess, rendered as an explicitly fenced block.
 *
 * Design intent: the refusal above stays the headline answer, and this reads as a clearly separate second
 * voice. The dashed border, the flask icon, and the mandatory confidence label are all there so a reader
 * cannot mistake general best practice for this company's own recorded experience. The backend also strips
 * any decision id the model invents, and says so below if it had to.
 */
export function GuessPanel({ guess }: { guess: GuessBlock }) {
  if (!guess?.available) return null;
  const conf = CONF[guess.confidence ?? "LOW"] ?? CONF.LOW;

  return (
    <div className="fade-up mt-6 border border-dashed border-[var(--rule-strong)] bg-[var(--paper-sunk)] px-4 py-3.5">
      <div className="flex items-center gap-2">
        <FlaskConical className="size-[14px] text-ink-faint" strokeWidth={1.8} />
        <Label>If I had to guess</Label>
        <span className={`ml-auto text-[11.5px] font-medium ${conf.className}`}>{conf.label}</span>
      </div>

      <p className="mt-2 text-[12.5px] text-ink-faint">
        not from your company&apos;s history — general practice only, no precedent cited
      </p>

      {guess.guess && (
        <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">{guess.guess}</p>
      )}

      {guess.watch && guess.watch.length > 0 && (
        <div className="mt-4">
          <Label>What would change it</Label>
          <ul className="mt-2 space-y-2">
            {guess.watch.map((w, i) => (
              <li key={i} className="flex gap-2.5 text-[13.5px] leading-relaxed text-ink-soft">
                <span className="mt-[7px] size-1 shrink-0 rounded-full bg-ink-faint" />
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {guess.stripped_fabricated_ids && (
        <p className="mt-3 text-[12px] text-risk-medium">
          the guess referenced a decision id it could not have known; that reference was removed
        </p>
      )}
      {guess.confidence_capped && (
        <p className="mt-3 text-[12px] text-ink-faint">
          confidence capped: an ungrounded guess cannot honestly claim high confidence
        </p>
      )}
    </div>
  );
}
