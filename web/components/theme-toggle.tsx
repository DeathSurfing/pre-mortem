"use client";
import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

const KEY = "pm-theme";
type Mode = "system" | "light" | "dark";
const ORDER: Mode[] = ["system", "light", "dark"];

const LABEL: Record<Mode, string> = {
  system: "Match your system",
  light: "Light",
  dark: "Dark",
};

function prefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function apply(mode: Mode) {
  const dark = mode === "dark" || (mode === "system" && prefersDark());
  document.documentElement.classList.toggle("dark", dark);
  // `color-scheme` so form controls and scrollbars follow, not just our tokens
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

/**
 * Three-way theme control: system (default) -> light -> dark -> system.
 *
 * `system` is the default because the product is meant to fit the reader's environment. It is also live:
 * when the OS preference changes while `system` is selected, the theme follows without a reload.
 */
export const themeScript = `(function(){try{
var k='${KEY}';
var s=localStorage.getItem(k);
var m=(s==='light'||s==='dark'||s==='system')?s:'system';
var d=m==='dark'||(m==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);
var r=document.documentElement;
if(d)r.classList.add('dark');
r.style.colorScheme=d?'dark':'light';
}catch(e){}})();`;


/**
 * Segmented three-way theme control for the sidebar. Shares the same storage key and apply() logic as the
 * cycle button, so the two can never disagree.
 */
export function ThemeChoice() {
  const [mode, setMode] = useState<Mode>("system");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(KEY) as Mode | null;
    setMode(stored && ORDER.includes(stored) ? stored : "system");
    setMounted(true);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      const cur = (localStorage.getItem(KEY) as Mode | null) ?? "system";
      if (cur === "system") apply("system");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  function pick(next: Mode) {
    setMode(next);
    apply(next);
    localStorage.setItem(KEY, next);
  }

  const ICON: Record<Mode, typeof Sun> = { system: Monitor, light: Sun, dark: Moon };

  return (
    <div className="mt-2 inline-flex w-full rounded-md border border-[var(--rule-strong)] p-[2px]" role="radiogroup" aria-label="Theme">
      {ORDER.map((m) => {
        const Icon = ICON[m];
        const active = mounted && mode === m;
        return (
          <button
            key={m}
            role="radio"
            aria-checked={active}
            onClick={() => pick(m)}
            className={
              "flex min-h-[40px] flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-[12.5px] transition-colors " +
              (active ? "bg-[var(--paper-sunk)] text-ink" : "text-ink-muted hover:text-ink")
            }
          >
            <Icon className="size-[13px]" strokeWidth={1.8} />
            <span className="capitalize">{m}</span>
          </button>
        );
      })}
    </div>
  );
}
