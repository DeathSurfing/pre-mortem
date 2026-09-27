/**
 * Typed client for the FastAPI service. The browser never talks to Hindsight directly.
 * Contract mirrors api/app/lookalike.py's Assessment dict.
 */

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export type Precedent = {
  launch_id: string | null;
  date: string;
  service: string | null;
  change_class: string | null;
  outcome: string | null;
  pattern_id: string | null;
  is_mirror: boolean;
  proof_count: number;
  trend: string;
  memory_id: string | null;
  memory_type: string | null;
  source_chunk: string | null;
  text: string | null;
  score: {
    proof: number;
    recency: number;
    trend_penalty: number;
    ledger_boost: number;
    total: number;
  };
};

export type Declined = {
  launch_id: string | null;
  service: string | null;
  change_class: string | null;
  reason: string;
  proof_count: number;
};

export type Flip = {
  precedent_launch_id?: string | null;
  differentiating_detail?: string | null;
  why_it_matters?: string | null;
  cited_fix?: string | null;
};

export type Assessment = {
  memory: boolean;
  preset: string;
  label: string;
  pending: { service: string; change_class: string; change: string; diff: string };
  risk: "high" | "medium" | "low" | "unknown";
  confidence: number;
  no_precedent: boolean;
  verdict_rules?: string;
  conflicting?: number;
  mirrors?: number;
  precedents: Precedent[];
  declined: Declined[];
  flip: Flip | null;
  baseline?: string | null;
  no_precedent_message?: string;
  facts_used: string[];
  ledger_promoted: string[];
  engine: {
    ranker: string;
    llm: string;
    llm_calls: number;
    model_used?: string;
    llm_error?: string;
    citation_warning?: string;
    engine?: string;
  };
  reflect?: { text?: string | null; based_on?: { id: string; text: string }[] };
};

export type Ledger = {
  flags: number;
  ignored: number;
  costed: number;
  promoted_classes: string[];
  rows: {
    launch_id: string;
    service: string;
    change_class: string;
    ignored: boolean;
    costed: boolean;
    text: string;
  }[];
};

export type PresetInfo = {
  key: string;
  label: string;
  service: string;
  change_class: string;
  change: string;
  diff: string;
  expect: string;
};

export type Metrics = {
  epochs: { epoch: number; launches: number; flagged_high: number }[];
  totals: {
    launches: number;
    found_precedent: number;
    found_coverage: number;
    derivable: number;
    derivable_coverage: number;
    gap: number;
  };
  method: string;
  rows: {
    launch_id: string;
    date: string;
    outcome: string;
    flagged_high: boolean;
    found_precedent: boolean;
    cited: string | null;
    derivable: boolean;
  }[];
};

export type Health = {
  ok: boolean;
  problems: string[];
  bank_id: string;
  models: { llm: string; fallback: string; min_proof: number };
  features?: { api_version?: string; observations?: boolean };
  bank?: { directives_total: number; corpus_expected: number };
  documents?: { id?: string; error?: string }[];
  error?: string;
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${path} -> ${r.status} ${body.slice(0, 220)}`);
  }
  return (await r.json()) as T;
}

export const api = {
  base: BASE,
  health: () => req<Health>("/health"),
  presets: () => req<PresetInfo[]>("/api/presets"),
  assess: (preset: string, memory: boolean, engine = "recall") =>
    req<Assessment>("/api/assess", {
      method: "POST",
      body: JSON.stringify({ preset, memory, engine }),
    }),
  ledger: () => req<Ledger>("/api/ledger"),
  metrics: () => req<Metrics>("/api/metrics"),
  bank: () => req<Record<string, unknown>>("/api/bank"),
  promptPreview: (operation = "retain") =>
    req<Record<string, unknown>>(`/api/prompt-preview?operation=${operation}`),
};
