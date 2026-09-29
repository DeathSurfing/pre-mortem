"use client";
import { ArrowUpRight, Mail } from "lucide-react";

/**
 * The gate shown once a visitor has spent their allowance.
 *
 * Replaces the composer rather than sitting beside it: the point is that no further prompt can be sent, and
 * a disabled-looking input invites people to keep trying. Everything already answered stays on screen above
 * this, because taking away a visitor's results to tell them about a limit reads as a bait-and-switch.
 *
 * The copy avoids the word "error". Running out is not a failure, it is the end of a free allowance, and a
 * sales conversation is the intended next step.
 */
export function ContactSales({
  limit,
  retryAfterSeconds,
  contactUrl,
  onDismiss,
}: {
  limit?: number;
  retryAfterSeconds?: number;
  /** Where an enquiry should go. Defaults to mailto so this works with no backend. */
  contactUrl?: string;
  /** Escape hatch for the demo: lets the reviewer keep the page usable without pretending the limit lifted. */
  onDismiss?: () => void;
}) {
  const href = contactUrl || "mailto:adityavikram@lexcontra.com?subject=pre-mortem%20access";
  const hours = retryAfterSeconds ? Math.max(1, Math.round(retryAfterSeconds / 3600)) : null;

  return (
    <section className="mx-auto w-full max-w-[1180px] px-4 pb-10 sm:px-6">
      <div className="border border-[var(--rule-strong)] bg-paper-raised px-5 py-6 sm:px-7 sm:py-7">
        <span className="label">Free reviews used</span>
        <h2 className="mt-2 font-display text-[22px] font-normal leading-snug text-ink sm:text-[26px]">
          You have used all {limit ?? 10} free reviews.
        </h2>
        <p className="mt-3 measure text-[14.5px] leading-relaxed text-ink-soft">
          Every review searches your recorded decisions and writes a cited answer, which costs real
          inference, so the free allowance is capped per visitor. Nothing you have already asked has been
          removed.
        </p>
        <p className="mt-2 measure text-[14.5px] leading-relaxed text-ink-soft">
          Get in touch and we will open it up.
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <a
            href={href}
            className="inline-flex min-h-[42px] items-center gap-2 rounded-md bg-accent px-4 text-[14px] text-white transition-opacity hover:bg-accent-deep"
          >
            <Mail className="size-[15px]" strokeWidth={2.2} />
            Contact us
          </a>
          <a
            href="https://lexcontra.com/"
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-[42px] items-center gap-1.5 rounded-md px-3 text-[14px] text-ink-muted transition-colors hover:text-ink"
          >
            lexcontra.com
            <ArrowUpRight className="size-[14px]" strokeWidth={2} />
          </a>
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="min-h-[42px] rounded-md px-3 text-[13px] text-ink-faint transition-colors hover:text-ink-muted"
            >
              I am the owner, keep going
            </button>
          )}
        </div>

        {hours !== null && hours > 1 && (
          <p className="mt-4 text-[12.5px] text-ink-faint">
            The allowance resets in about {hours} {hours === 1 ? "hour" : "hours"}.
          </p>
        )}
      </div>
    </section>
  );
}
