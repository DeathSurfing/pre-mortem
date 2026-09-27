"use client";
import { useCallback, useEffect, useState } from "react";

export type Density = "comfortable" | "compact";

export type Settings = {
  /** Read the evidence records inline by default, or keep them behind the pills. */
  sourcesOpen: boolean;
  /** Spacing of the citation list. */
  density: Density;
  /** Show the engine line (which component produced what). */
  showEngine: boolean;
};

const KEY = "pm-settings";

export const DEFAULT_SETTINGS: Settings = {
  sourcesOpen: false,
  density: "comfortable",
  showEngine: false,
};

/**
 * Display settings, persisted to localStorage.
 *
 * Deliberately a tiny hook rather than a store: four booleans do not need a dependency. Reads once on
 * mount (never during render, so SSR and the first client render agree), then writes on change.
 */
export function useSettings() {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) setSettings({ ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<Settings>) });
    } catch {
      /* corrupt value: fall back to defaults rather than breaking the app */
    }
    setLoaded(true);
  }, []);

  const update = useCallback(<K extends keyof Settings>(k: K, v: Settings[K]) => {
    setSettings((prev) => {
      const next = { ...prev, [k]: v };
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* private mode: keep the in-memory value */
      }
      return next;
    });
  }, []);

  return { settings, update, loaded };
}
