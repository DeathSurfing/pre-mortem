"""Prompt store: every prompt ever run, vectorised, for cross-referencing across prompts.

Why Postgres and not Hindsight: Hindsight is the company's curated decision memory, and it is the thing
the product reasons over. A prompt the user typed is not company knowledge. Mixing the two would let
unreviewed text enter the evidence the ranker cites. So prompts live here, in a separate store, and the
only bridge between them is the explicit "Commit to knowledge base" action, which calls Hindsight
`retain` where the user asked for it.

Design constraints that shaped this file:

- **Degrade, never break.** The review path is the product. If Postgres is unreachable, every function
  here returns empty/None and logging records it; the review still streams. Same discipline as Laya.
- **No new dependency for embeddings.** `transformers` + `torch` are already in the image because Laya
  needs them, and 9router exposes no embeddings route (verified). So embeddings run locally on CPU.
- **Embedding is never fatal.** A prompt is recorded even if its vector fails; `embedded_at` stays NULL
  and a later pass can catch up. Losing the vector must not lose the prompt.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any

log = logging.getLogger("premortem.prompts")

DEFAULT_DSN = "postgresql://premortem:premortem@postgres:5432/premortem"

# bge-small-en-v1.5 is 384-dimensional. Changing the model changes this, and the column is typed with it,
# so the two must move together.
EMBED_DIM = 384
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS prompts (
    id            uuid PRIMARY KEY,
    prompt        text NOT NULL,
    domain        text,
    decision_type text,
    mode          text,
    risk          text,
    confidence    double precision,
    session_id    text,
    committed     boolean NOT NULL DEFAULT false,
    hindsight_doc text,
    embedding     vector({EMBED_DIM}),
    created_at    timestamptz NOT NULL DEFAULT now(),
    embedded_at   timestamptz
);
CREATE INDEX IF NOT EXISTS prompts_created_idx ON prompts (created_at DESC);
CREATE INDEX IF NOT EXISTS prompts_session_idx ON prompts (session_id, created_at DESC);
-- HNSW: adequate at this scale and needs no training pass, unlike ivfflat which wants data first.
CREATE INDEX IF NOT EXISTS prompts_embedding_idx ON prompts
    USING hnsw (embedding vector_cosine_ops);
"""

_COSINE_CUTOFF = float(os.getenv("PROMPT_SIM_CUTOFF", "0.35"))


def _dsn() -> str:
    return os.getenv("PROMPT_DB_URL", "") or os.getenv("DATABASE_URL", "") or DEFAULT_DSN


class PromptStore:
    """Thin psycopg layer. One connection per call: this is a low-QPS store, so a pool is not worth it."""

    def __init__(self) -> None:
        self.error: str | None = None
        self._schema_ready = False
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- connection

    def _connect(self):
        import psycopg
        return psycopg.connect(_dsn(), connect_timeout=5, autocommit=True)

    def ensure_schema(self) -> bool:
        """Idempotent. True when the table exists and is ready to use."""
        if self._schema_ready:
            return True
        with self._lock:
            if self._schema_ready:
                return True
            try:
                with self._connect() as conn, conn.cursor() as cur:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                    cur.execute(SCHEMA)
                self._schema_ready = True
                self.error = None
                return True
            except Exception as e:  # noqa: BLE001 - any failure means "store unavailable"
                self.error = f"{type(e).__name__}: {e}"
                log.warning("prompt store unavailable: %s", self.error)
                return False

    def healthy(self) -> bool:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("select 1")
            self.error = None
            return True
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            return False

    # ---------------------------------------------------------------- write

    def record(self, *, prompt: str, domain: str | None = None, decision_type: str | None = None,
               mode: str | None = None, risk: str | None = None, confidence: float | None = None,
               session_id: str | None = None, embedding: list[float] | None = None) -> str | None:
        """Insert one prompt. Returns the id, or None when the store is down.

        `committed` is deliberately False: recording a prompt does NOT put it in the company's knowledge
        base. That only happens through `commit`, and only because a person said so.
        """
        if not self.ensure_schema():
            return None
        pid = str(uuid.uuid4())
        embedded_at = datetime.now(timezone.utc) if embedding is not None else None
        try:
            with self._connect() as conn, conn.cursor() as cur:
                # `%s::vector` and an explicitly-passed timestamp, not a `case when %s is null` in SQL:
                # Postgres cannot infer the type of a bare NULL parameter there and rejects the whole
                # insert with IndeterminateDatatype, which lost the prompt rather than just its vector.
                cur.execute(
                    """insert into prompts
                       (id, prompt, domain, decision_type, mode, risk, confidence, session_id,
                        embedding, embedded_at)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s)""",
                    (pid, prompt, domain, decision_type, mode, risk, confidence, session_id,
                     embedding, embedded_at),
                )
            return pid
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            log.warning("prompt record failed: %s", self.error)
            return None

    def commit(self, prompt_id: str, hindsight_doc: str | None) -> bool:
        """Mark a prompt as committed to the knowledge base, recording the Hindsight document id."""
        if not self.ensure_schema():
            return False
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("update prompts set committed = true, hindsight_doc = %s where id = %s",
                            (hindsight_doc, prompt_id))
                return cur.rowcount > 0
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            log.warning("prompt commit failed: %s", self.error)
            return False

    # ---------------------------------------------------------------- read

    @staticmethod
    def _jsonable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Coerce driver types to JSON-safe primitives.

        psycopg returns `uuid.UUID` for id and `datetime` for timestamps. Those survive a Python dict but
        blow up in `json.dumps`, which is how these rows travel (SSE events and the REST endpoints), so the
        coercion belongs here rather than at every call site.
        """
        for r in rows:
            for k, v in list(r.items()):
                if isinstance(v, uuid.UUID):
                    r[k] = str(v)
                elif isinstance(v, (datetime, date)):
                    r[k] = v.isoformat()
        return rows

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.ensure_schema():
            return []
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """select id, prompt, domain, decision_type, mode, risk, confidence, committed,
                              created_at, (embedding is not null) as has_vector
                       from prompts order by created_at desc limit %s""", (limit,))
                cols = [c.name for c in cur.description]
                return self._jsonable([dict(zip(cols, r)) for r in cur.fetchall()])
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            return []

    def similar(self, embedding: list[float], *, limit: int = 5, exclude_id: str | None = None,
                include_unembedded: bool = False) -> list[dict[str, Any]]:
        """Nearest prior prompts by cosine distance.

        `include_unembedded` defaults to False because an empty vector is not a similarity: rows with a
        NULL embedding are reported in a separate bucket by `cross_reference` rather than ranked at some
        misleading distance.
        """
        if not self.ensure_schema():
            return []
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """select id, prompt, domain, decision_type, mode, risk, confidence, committed,
                              created_at, 1 - (embedding <=> %s::vector) as similarity
                       from prompts
                       where embedding is not null
                         and (%s::uuid is null or id <> %s::uuid)
                       order by embedding <=> %s::vector
                       limit %s""",
                    (embedding, exclude_id, exclude_id, embedding, limit))
                cols = [c.name for c in cur.description]
                rows = self._jsonable([dict(zip(cols, r)) for r in cur.fetchall()])
            # A no-precedent prompt is still a real prompt, so nothing is filtered out here; the cutoff
            # only labels, so a weak match is visible as weak rather than silently dropped.
            for r in rows:
                r["above_cutoff"] = float(r["similarity"]) >= _COSINE_CUTOFF
            return rows
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            log.warning("prompt similarity failed: %s", self.error)
            return []

    def stats(self) -> dict[str, Any]:
        if not self.ensure_schema():
            return {"available": False, "error": self.error}
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("""select count(*) as total,
                                      count(embedding) as embedded,
                                      count(*) filter (where committed) as committed
                               from prompts""")
                total, embedded, committed = cur.fetchone()
            return {"available": True, "total": total, "embedded": embedded, "committed": committed,
                    "model": EMBED_MODEL, "dim": EMBED_DIM}
        except Exception as e:  # noqa: BLE001
            return {"available": False, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------- embeddings

_model = None
_model_lock = threading.Lock()
_model_error: str | None = None


def _load_model():
    """bge-small-en-v1.5 on CPU. `transformers` is already in the image for Laya, so this adds no dep."""
    global _model, _model_error
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from transformers import AutoModel, AutoTokenizer
            tok = AutoTokenizer.from_pretrained(EMBED_MODEL)
            mdl = AutoModel.from_pretrained(EMBED_MODEL)
            mdl.eval()
            _model = (tok, mdl)
            _model_error = None
        except Exception as e:  # noqa: BLE001
            _model_error = f"{type(e).__name__}: {e}"
            log.warning("embedding model unavailable: %s", _model_error)
            return None
    return _model


def embed(text: str) -> list[float] | None:
    """Mean-pooled, L2-normalised embedding. None when the model is unavailable, which is not an error.

    Normalised so cosine distance is the honest metric, and bge wants a query prefix for retrieval; for
    symmetric prompt-to-prompt comparison no prefix is used on either side.
    """
    loaded = _load_model()
    if loaded is None:
        return None
    tok, mdl = loaded
    try:
        import torch
        with torch.no_grad():
            batch = tok([text], padding=True, truncation=True, max_length=512, return_tensors="pt")
            out = mdl(**batch)
            # CLS pooling is what bge was trained with.
            vec = out.last_hidden_state[:, 0]
            vec = torch.nn.functional.normalize(vec, p=2, dim=1)
        return [float(x) for x in vec[0]]
    except Exception as e:  # noqa: BLE001
        log.warning("embed failed: %s: %s", type(e).__name__, e)
        return None


def embedding_status() -> dict[str, Any]:
    return {"model": EMBED_MODEL, "dim": EMBED_DIM, "loaded": _model is not None, "error": _model_error}


def new_session_id() -> str:
    return uuid.uuid4().hex[:16]


def commit_document_text(prompt: str, *, domain: str | None, decision_type: str | None,
                         risk: str | None, created_at: datetime | None = None) -> tuple[str, dict[str, Any]]:
    """The document text sent to Hindsight when a user commits a prompt.

    Shaped as a decision record, not a chat log, because Hindsight's extraction prompt looks for what was
    decided, the rationale, the result and the lesson. Metadata is kept flat and string-valued.
    """
    ts = (created_at or datetime.now(timezone.utc)).date().isoformat()
    did = f"U-{ts}-{uuid.uuid4().hex[:6]}"
    body = (
        f"User-recorded decision, submitted {ts}. Decision id {did}.\n"
        f"Area: {domain or 'unclassified'} / {decision_type or 'unclassified'}.\n"
        f"Reviewer's risk reading at the time: {risk or 'not recorded'}.\n\n"
        f"The decision the user is considering:\n{prompt}\n"
    )
    meta = {"decision_id": did, "source": "user_committed", "domain": domain or "unclassified",
            "decision_type": decision_type or "unclassified", "risk": risk or "not recorded"}
    return did, {"text": body, "metadata": {k: str(v) for k, v in meta.items()}}


def decision_document_text(
    *,
    decision: str,
    domain: str | None,
    decision_type: str | None,
    rationale: str | None = None,
    result: str | None = None,
    lesson: str | None = None,
    outcome: str | None = None,
    owner: str | None = None,
    scale: str | None = None,
    context: str | None = None,
    source_prompt: str | None = None,
    created_at: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """The document text Hindsight receives when a user adds a decision.

    Mirrors the shape of the seeded corpus records (`bizcorpus.Decision.text`) so a user-added decision is
    retrievable on the same terms as a seeded one: area, date, owner, amount, context, decision, rationale,
    result, lesson. Hindsight's extraction prompt looks for exactly those, so a differently shaped document
    extracts worse facts.

    `outcome` is written as "not-recorded" when unknown, and the body says so in words. A decision the user
    is still weighing has no result, and inventing one would put a fabricated precedent into the very store
    the product cites. `rank.verdict` already treats a missing outcome as neither good nor bad, so an
    unresolved record can support a review but can never inflate or deflate risk.
    """
    ts = (created_at or datetime.now(timezone.utc)).date().isoformat()
    did = f"U-{ts}-{uuid.uuid4().hex[:6]}"
    parts = [
        f"Business decision {did} | {domain or 'unclassified'} | {decision_type or 'unclassified'}",
        f"Recorded by the user on: {ts}",
    ]
    if owner:
        parts.append(f"Owner: {owner}")
    if scale:
        parts.append(f"Amount at stake: {scale}")
    if context:
        parts.append(f"Context at the time: {context}")
    if source_prompt:
        parts.append(f"If it were a review question, it would read: {source_prompt}")
    parts.append(f"Decision: {decision}")
    parts.append(f"Rationale at the time: {rationale or 'not recorded'}")
    # The result is not knowable yet in the common case, and saying so is the honest record.
    parts.append(f"Result: {result or 'not yet known; this decision had not been carried out when recorded'}")
    if lesson:
        parts.append(f"Lesson recorded: {lesson}")
    if not outcome:
        parts.append(
            "Note: no outcome is recorded for this decision yet. Do not treat it as having gone well or "
            "badly. It is context, not evidence of a result."
        )
    meta = {
        "decision_id": did,
        "source": "user_added",
        "domain": domain or "unclassified",
        "decision_type": decision_type or "unclassified",
        "outcome": outcome or "not-recorded",
        "owner": owner or "",
        "scale": scale or "",
        "date": ts,
    }
    return did, {"text": "\n".join(parts), "metadata": {k: str(v) for k, v in meta.items()}}


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)
