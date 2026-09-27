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
export function ThemeToggle() {
  const [mode, setMode] = useState<Mode>("system");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(KEY) as Mode | null;
    const initial: Mode = stored && ORDER.includes(stored) ? stored : "system";
    setMode(initial);
    apply(initial);
    setMounted(true);

    // follow the OS while in system mode
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if ((localStorage.getItem(KEY) as Mode | null) === "system" || !localStorage.getItem(KEY)) {
        apply("system");
      }
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  function cycle() {
    const next = ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
    setMode(next);
    apply(next);
    localStorage.setItem(KEY, next);
  }

  const Icon = mode === "system" ? Monitor : mode === "dark" ? Moon : Sun;

  return (
    <button
      onClick={cycle}
      aria-label={`Theme: ${LABEL[mode]}. Click to change.`}
      title={`${LABEL[mode]} — click to cycle system / light / dark`}
      className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] text-ink-muted transition-colors hover:bg-[var(--paper-sunk)] hover:text-ink"
    >
      <Icon className="size-[14px]" strokeWidth={1.8} />
      <span className="hidden sm:inline">{LABEL[mode].split(" ")[0].toLowerCase()}</span>
      {!mounted && <span className="sr-only">loading theme</span>}
    </button>
  );
}

/**
 * Inline script, run before first paint, so the stored mode is applied without a flash.
 * Kept synchronous and dependency-free on purpose: anything async here defeats the point.
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
