"use client";
import { useState } from "react";
import { Brain, ChevronRight } from "lucide-react";
import { Label } from "@/components/editorial";
import { cn } from "@/lib/utils";

/**
 * The model's reasoning trace, collapsed by default.
 *
 * This is a real stream the model already produces (OpenCode Go emits `reasoning_content` deltas before
 * `content`). It used to be discarded. Shown collapsed because it is genuinely useful when someone wants to
 * check how a verdict was reached, but it is not the answer and should never compete with it.
 */
export function Thinking({ text, busy }: { text: string; busy?: boolean }) {
  const [open, setOpen] = useState(false);
  if (!text.trim()) return null;

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="group inline-flex items-center gap-2 text-[12px] text-ink-faint transition-colors hover:text-ink-muted"
      >
        <ChevronRight
          className={cn("size-[12px] transition-transform", open && "rotate-90")}
          strokeWidth={2}
        />
        <Brain className="size-[12.5px]" strokeWidth={1.8} />
        <span>
          {busy ? "thinking" : "reasoning"}
          {busy && <span className="caret ml-1" />}
        </span>
        {!open && (
          <span className="font-mono text-[11px] opacity-70">{text.trim().length} chars</span>
        )}
      </button>

      {open && (
        <div className="fade-up mt-2 border-l-2 border-[var(--rule-strong)] pl-3.5">
          <Label>The model&apos;s thinking, not the answer</Label>
          <p className="mt-2 max-h-[22rem] overflow-y-auto whitespace-pre-wrap text-[12.5px] leading-relaxed text-ink-faint">
            {text}
          </p>
        </div>
      )}
    </div>
  );
}
