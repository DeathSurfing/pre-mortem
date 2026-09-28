/**
 * Typed client for the business red-flagger, including the SSE stream.
 *
 * The stream is consumed with fetch + ReadableStream rather than EventSource, because EventSource cannot
 * send a request body and cannot POST. Events arrive as `data: {...}\n\n`.
 */

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export type LayaSignals = {
  domain_probability: number | null;
  domain_confidence: number | null;
  reversibility_score: number | null;
  reversibility_label: string | null;
  gives_value_without_commitment: number | null;
  is_high_blast_radius: number | null;
};

export type Precedent = {
  launch_id: string;
  date: string;
  domain: string | null;
  decision_type: string | null;
  outcome: string | null;
  is_mirror: boolean;
  proof_count: number;
  attribution_ok: boolean;
  text: string;
};

export type Declined = {
  launch_id: string;
  domain: string | null;
  decision_type: string | null;
  proof_count: number;
  reason: string;
};

export type Opinion = {
  headline: string | null;
  why: string | null;
  differentiating_detail: string | null;
  suggested_guardrail: string | null;
  open_questions: string[];
};

export type StreamEvent =
  | { type: "status"; message: string; step: string }
  | { type: "ledger"; promoted: string[] }
  | { type: "classify"; domain: string; decision_type: string; mode?: "decision" | "chat" | "query"; follow_up?: boolean; intent: string; rationale: string; laya: LayaSignals | null }
  | { type: "verdict"; risk: "high" | "medium" | "low" | "unknown"; confidence: number; no_precedent: boolean; rules: string; relaxed: boolean }
  | { type: "precedents"; precedents: Precedent[]; declined: Declined[] }
  | { type: "delta"; text: string }
  | { type: "reasoning"; text: string }
  | ({ type: "guess" } & GuessBlock)
  /** Emitted after the answer when the prompt was recorded in the prompt store. `similar` is the
   *  cross-reference: prior prompts that look like this one. `committed` is always false here; committing
   *  is a separate, explicit user action (POST /api/biz/prompts/commit). */
  | { type: "prompt_recorded"; id: string | null; embedded: boolean; similar: SimilarPrompt[] }
  | { type: "done"; opinion?: Opinion | null; engine: Record<string, unknown>; facts_used: string[]; citations_in_prose: string[]; uncited_facts?: string[]; attribution_unverified?: string[] }
  | { type: "error"; message: string };

export type DecisionDraft = {
  decision: string;
  rationale: string;
  result: string;
  lesson: string;
  /** "" when the outcome is not known. Allowed non-empty: good | mixed | bad. Never inferred. */
  outcome: string;
  owner: string;
  scale: string;
  context: string;
  domain: string;
  decision_type: string;
};

export type SimilarPrompt = {
  id: string;
  prompt: string;
  domain: string | null;
  decision_type: string | null;
  risk: string | null;
  committed: boolean;
  similarity: number;
  /** False when cosine similarity is below the cutoff. Kept visible and labelled rather than hidden, so
   *  a first-of-its-kind prompt still shows what it was compared against. */
  above_cutoff: boolean;
  created_at?: string;
};

/**
 * A no-precedent guess. Deliberately a distinct shape from Opinion: the UI renders it in its own fenced
 * block so a general-model opinion is never displayed as if it were company memory.
 */
export type Health = {
  ok: boolean;
  problems: string[];
  bank_id: string;
  laya?: { enabled?: boolean; loaded?: boolean; error?: string | null };
  models?: { llm?: string; fallback?: string };
  features?: Record<string, unknown>;
};

export type GuessBlock = {
  available: boolean;
  reason?: string;
  verdict?: string;
  guess?: string;
  confidence?: "LOW" | "MEDIUM" | "HIGH";
  watch?: string[];
  domain?: string;
  decision_type?: string;
  stripped_fabricated_ids?: boolean;
  confidence_capped?: boolean;
};

export type PromptPreset = {
  key: string;
  label: string;
  text: string;
  expect_domain: string;
  expect_type: string;
  expect: string;
};

export type Ledger = {
  flags: number;
  ignored: number;
  costed: number;
  promoted_classes: string[];
  rows: { decision_id: string; domain: string; decision_type: string; ignored: boolean; costed: boolean; text: string }[];
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`${path} -> ${r.status} ${(await r.text()).slice(0, 200)}`);
  return (await r.json()) as T;
}

/** Parse an SSE byte stream into typed events, invoking onEvent as each arrives. */
export type HistoryTurn = { role: "user" | "assistant"; content: string };

/** How many prior turns to send. Enough for continuity, bounded so the request cannot grow without limit. */
const HISTORY_LIMIT = 12;

export async function streamRedflag(
  prompt: string,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
  history: HistoryTurn[] = [],
): Promise<void> {
  // POST rather than GET: a follow-up carries the preceding conversation, which will not survive a query
  // string. `preset` keeps working through the body.
  const res = await fetch(`${BASE}/api/biz/redflag/stream`, {
    method: "POST",
    headers: { accept: "text/event-stream", "content-type": "application/json" },
    body: JSON.stringify({ prompt, history: history.slice(-HISTORY_LIMIT) }),
    signal,
    cache: "no-store",
  });
  if (!res.ok || !res.body) {
    throw new Error(`stream -> ${res.status} ${(await res.text()).slice(0, 200)}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    // events are separated by a blank line
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of raw.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        try {
          onEvent(JSON.parse(payload) as StreamEvent);
        } catch {
          /* ignore malformed frame */
        }
      }
    }
  }
}

export const api = {
  base: BASE,
  health: () => req<Health>("/health"),
  prompts: () => req<PromptPreset[]>("/api/biz/prompts"),
  ledger: () => req<Ledger>("/api/biz/ledger"),
  bank: () => req<Record<string, unknown>>("/api/biz/bank"),
};

/**
 * Prompt store. Separate from Hindsight by design: recording is automatic, committing is a human choice.
 */
export const promptStore = {
  list: (limit = 20) =>
    req<{ available: boolean; items: SimilarPrompt[]; stats: Record<string, unknown> }>(
      `/api/biz/history?limit=${limit}`),
  stats: () => req<Record<string, unknown>>("/api/biz/history/stats"),
  /** Cross-reference arbitrary text without recording it. */
  recall: (prompt: string, limit = 5) =>
    req<{ similar: SimilarPrompt[] }>("/api/biz/history/recall", {
      method: "POST",
      body: JSON.stringify({ prompt, limit }),
    }),
  /** Draft a decision record from the review, for the user to edit before adding. */
  draft: (body: { prompt: string; domain?: string | null; decision_type?: string | null; risk?: string | null; headline?: string | null }) =>
    req<{ draft: DecisionDraft; drafted: boolean; domains: string[]; decision_types: string[]; note: string }>(
      "/api/biz/history/draft", { method: "POST", body: JSON.stringify(body) }),
  /** The one path that writes a decision into the company knowledge base. */
  commit: (body: {
    id?: string | null;
    prompt?: string;
    domain?: string | null;
    decision_type?: string | null;
    risk?: string | null;
    /** Present when the user filled in / edited the record. Absent stores the thinner prompt-only record. */
    draft?: DecisionDraft;
  }) =>
    req<{ committed: boolean; decision_id: string; outcome_recorded?: boolean }>("/api/biz/history/commit", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
