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
  | { type: "classify"; domain: string; decision_type: string; intent: string; rationale: string; laya: LayaSignals | null }
  | { type: "verdict"; risk: "high" | "medium" | "low" | "unknown"; confidence: number; no_precedent: boolean; rules: string; relaxed: boolean }
  | { type: "precedents"; precedents: Precedent[]; declined: Declined[] }
  | { type: "delta"; text: string }
  | { type: "done"; opinion?: Opinion | null; engine: Record<string, unknown>; facts_used: string[]; citations_in_prose: string[]; uncited_facts?: string[]; attribution_unverified?: string[] }
  | { type: "error"; message: string };

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
export async function streamRedflag(
  prompt: string,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const url = `${BASE}/api/biz/redflag/stream?prompt=${encodeURIComponent(prompt)}`;
  const res = await fetch(url, { headers: { accept: "text/event-stream" }, signal, cache: "no-store" });
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
  health: () => req<Record<string, unknown>>("/health"),
  prompts: () => req<PromptPreset[]>("/api/biz/prompts"),
  ledger: () => req<Ledger>("/api/biz/ledger"),
  bank: () => req<Record<string, unknown>>("/api/biz/bank"),
};
