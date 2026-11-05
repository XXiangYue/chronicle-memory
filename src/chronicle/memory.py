"""Chronicle: eligible sources, append-only corrections and evidence-budgeted QA.

The eligibility-before-ranking principle adapts changjuan Retrieval.search;
chapter-specific identifiers have been replaced with source/known-time contracts.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import threading
from pathlib import Path

import numpy as np

from .common import ROOT, db, digest, write_json
from .model import Model, estimate_tokens

_models = {}
_embedding_cache = {}
_embed_lock = threading.Lock()


def instant(value):
    if not value:
        return "9999-12-31T23:59:59"
    value = str(value)
    for fmt in (
        "%Y/%m/%d (%a) %H:%M",
        "%Y/%m/%d (%a)",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return dt.datetime.strptime(value, fmt).isoformat()
        except ValueError:
            pass
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(dt.timezone.utc)
        return parsed.replace(tzinfo=None).isoformat()
    except ValueError:
        raise ValueError("Unsupported timestamp: " + value)


def tokens(text):
    # Deterministic lexical stage. Chinese bigrams follow the original project's
    # invented-name strategy; the second stage uses a real language-specific BGE.
    terms = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    for word in re.findall(r"[\u4e00-\u9fff]+", text):
        terms.extend(word[i : i + 2] for i in range(max(1, len(word) - 1)))
    return list(dict.fromkeys(terms))


def embedding(texts, language, *, cache_namespace="setup"):
    name = "BAAI/bge-small-zh-v1.5" if language == "zh" else "BAAI/bge-small-en-v1.5"
    with _embed_lock:
        if name not in _models:
            from fastembed import TextEmbedding

            _models[name] = TextEmbedding(
                name, cache_dir=str(ROOT / "models/fastembed"), threads=2
            )
        model = _models[name]
        keys = [(name, cache_namespace, digest(t)) for t in texts]
        missing = list(
            dict.fromkeys(
                (key, text)
                for key, text in zip(keys, texts)
                if key not in _embedding_cache
            )
        )
        if missing:
            vectors = list(model.embed([t for _, t in missing]))
            for (key, _), vector in zip(missing, vectors):
                _embedding_cache[key] = np.asarray(vector, dtype=np.float32)
        result = np.asarray([_embedding_cache[k] for k in keys], dtype=np.float32)
        if len(_embedding_cache) > 50000:
            _embedding_cache.clear()
    result /= np.maximum(np.linalg.norm(result, axis=1, keepdims=True), 1e-12)
    return result


class Memory:
    def __init__(self, path: Path, namespace: str):
        self.path, self.namespace = path, namespace
        with db(path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, namespace TEXT, observed_at TEXT, text TEXT, deleted INTEGER DEFAULT 0, hash TEXT)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, namespace TEXT, source_id TEXT, text TEXT, quote TEXT, valid_from TEXT, supersedes TEXT, claim_key TEXT, derived_known_at TEXT, dependencies TEXT, FOREIGN KEY(source_id) REFERENCES sources(id))"
            )
            c.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(source_id UNINDEXED, text, lexical)"
            )

    def ingest(self, sources):
        with db(self.path) as c:
            for s in sources:
                row = c.execute(
                    "SELECT * FROM sources WHERE id=?", (s["id"],)
                ).fetchone()
                values = (
                    s["id"],
                    self.namespace,
                    instant(s["observed_at"]),
                    s["text"],
                    int(s.get("deleted", False)),
                    digest(s["text"]),
                )
                if row:
                    if (
                        row["hash"] != values[-1]
                        or row["namespace"] != self.namespace
                        or row["observed_at"] != values[2]
                    ):
                        raise ValueError(
                            "Source identity/content cannot be overwritten"
                        )
                    if s.get("deleted"):
                        c.execute("UPDATE sources SET deleted=1 WHERE id=?", (s["id"],))
                    continue
                c.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)", values)
                text = s["text"]
                for pos in range(0, len(text), 1200):
                    chunk = text[max(0, pos - 180) : pos + 1200]
                    c.execute(
                        "INSERT INTO chunks VALUES(?,?,?)",
                        (s["id"], chunk, " ".join(tokens(chunk))),
                    )

    def delete(self, source_id):
        # SQL eligibility remains authoritative even before physical FTS cleanup.
        with db(self.path) as c:
            c.execute(
                "UPDATE sources SET deleted=1 WHERE id=? AND namespace=?",
                (source_id, self.namespace),
            )

    def sources(self, known_at):
        with db(self.path) as c:
            return [
                dict(x)
                for x in c.execute(
                    "SELECT * FROM sources WHERE namespace=? AND observed_at<=? AND deleted=0 ORDER BY observed_at,id",
                    (self.namespace, instant(known_at)),
                )
            ]

    def extract(self, model: Model, *, max_tokens=4096):
        sources = self.sources(None)
        public = [{k: s[k] for k in ("id", "observed_at", "text")} for s in sources]
        system = 'You maintain durable cross-session memory. You do NOT receive any questions or answer labels. Extract specific user facts, preferences, decisions, constraints, dates and explicit corrections; omit generic advice and chit-chat. Return JSON {"notes":[{"source_id":str,"claim_key":str,"fact":str,"quote":str,"valid_from":str|null,"supersedes_source_id":str|null}]}. claim_key is a stable subject/attribute key shared by corrections of that same fact, not by unrelated facts. Every quote must be a verbatim substring of its own source; preserve names/numbers. Use observed_at when no effective date is explicit. A correction does not erase earlier history. Do not infer facts that are absent. Prefer compact facts over summaries. Preserve the source language.'
        value, usage = model.json(
            system,
            json.dumps(public, ensure_ascii=False),
            max_tokens=max_tokens,
            label="memory_ingest:" + self.namespace,
        )
        by_id = {s["id"]: s for s in sources}
        accepted, rejected = [], []
        for note in value.get("notes", []):
            sid = note.get("source_id")
            quote = note.get("quote", "")
            if (
                sid not in by_id
                or not quote
                or quote not in by_id[sid]["text"]
                or not note.get("fact")
            ):
                rejected.append(note)
                continue
            try:
                valid = instant(note.get("valid_from") or by_id[sid]["observed_at"])
            except ValueError:
                valid = by_id[sid]["observed_at"]
            supersedes = note.get("supersedes_source_id")
            if supersedes and supersedes not in by_id:
                supersedes = None
            derived_known_at = max(s["observed_at"] for s in sources)
            dependencies = sorted(by_id)
            key = digest(
                [sid, note["fact"], valid, supersedes, derived_known_at, dependencies]
            )
            with db(self.path) as c:
                c.execute(
                    "INSERT OR IGNORE INTO notes VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        key,
                        self.namespace,
                        sid,
                        note["fact"],
                        quote,
                        valid,
                        supersedes,
                        note.get("claim_key", key),
                        derived_known_at,
                        json.dumps(dependencies),
                    ),
                )
            accepted.append(dict(note, id=key, valid_from=valid))
        return {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "rejected_notes": rejected,
            "model_usage": usage,
            "public_source_hash": digest(public),
        }

    def add_note(
        self, source_id, fact, quote, valid_from=None, supersedes=None, claim_key="fact"
    ):
        """Explicit ingestion API; used by callers/tests, never populated from QA gold."""
        with db(self.path) as c:
            s = c.execute(
                "SELECT * FROM sources WHERE id=? AND namespace=?",
                (source_id, self.namespace),
            ).fetchone()
            if not s or quote not in s["text"]:
                raise ValueError("A note needs its own source quote")
            c.execute(
                "INSERT OR IGNORE INTO notes VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    digest([source_id, fact]),
                    self.namespace,
                    source_id,
                    fact,
                    quote,
                    instant(valid_from or s["observed_at"]),
                    supersedes,
                    claim_key,
                    s["observed_at"],
                    json.dumps([source_id]),
                ),
            )

    def context(self, question, arm, known_at, as_of, language, *, evidence_cap=8192):
        eligible = self.sources(known_at)
        by_id = {s["id"]: s for s in eligible}
        as_of = instant(as_of or known_at)
        if arm == "M0":
            rows = [
                {"source_id": s["id"], "date": s["observed_at"], "text": s["text"]}
                for s in reversed(eligible)
            ]
        else:
            has_notes = False
            query = " OR ".join(
                '"' + x.replace('"', "") + '"' for x in tokens(question)[:60]
            )
            with db(self.path) as c:
                raw = (
                    list(
                        c.execute(
                            "SELECT chunks.source_id,chunks.text,bm25(chunks) score FROM chunks JOIN sources s ON s.id=chunks.source_id WHERE chunks MATCH ? AND s.namespace=? AND s.observed_at<=? AND s.deleted=0 ORDER BY score LIMIT 24",
                            (query, self.namespace, instant(known_at)),
                        )
                    )
                    if query
                    else []
                )
                # Ranking cannot bring back deleted/future/out-of-scope sources.
                rows = [
                    {
                        "source_id": r["source_id"],
                        "date": by_id[r["source_id"]]["observed_at"],
                        "text": r["text"],
                    }
                    for r in raw
                    if r["source_id"] in by_id
                ][:24]
                if arm == "M2":
                    notes = [
                        dict(n)
                        for n in c.execute(
                            "SELECT n.* FROM notes n JOIN sources s ON n.source_id=s.id WHERE n.namespace=? AND s.deleted=0 AND s.observed_at<=? AND n.derived_known_at<=? AND n.valid_from<=?",
                            (
                                self.namespace,
                                instant(known_at),
                                instant(known_at),
                                as_of,
                            ),
                        )
                    ]
                    notes = [
                        n
                        for n in notes
                        if set(json.loads(n["dependencies"])) <= set(by_id)
                    ]
                    # Corrections are resolved only among notes the system knew at
                    # query time. Old records are never retroactively truncated.
                    superseded = {
                        (n["supersedes"], n["claim_key"])
                        for n in notes
                        if n["supersedes"]
                    }
                    notes = [
                        n
                        for n in notes
                        if (n["source_id"], n["claim_key"]) not in superseded
                        and n["source_id"] in by_id
                    ]
                    has_notes = bool(notes)
                    q = set(tokens(question))
                    notes.sort(
                        key=lambda n: len(q & set(tokens(n["text"]))), reverse=True
                    )
                    rows = [
                        {
                            "source_id": n["source_id"],
                            "date": by_id[n["source_id"]]["observed_at"],
                            "text": n["text"],
                            "quote": n["quote"],
                            "valid_from": n["valid_from"],
                        }
                        for n in notes[:32]
                    ] + rows
            if not rows:
                rows = [
                    {
                        "source_id": s["id"],
                        "date": s["observed_at"],
                        "text": s["text"][:1200],
                    }
                    for s in reversed(eligible[-8:])
                ]
            if rows:
                vectors = embedding(
                    [question] + [r["text"] for r in rows],
                    language,
                    cache_namespace=arm,
                )
                similarity = vectors[1:] @ vectors[0]
                rows = [
                    r
                    for _, r in sorted(
                        zip(similarity.tolist(), rows), key=lambda p: p[0], reverse=True
                    )
                ]
                if arm == "M2" and has_notes:
                    seen, compact = set(), []
                    for row in rows:
                        key = (row["source_id"], row["text"])
                        if key not in seen:
                            compact.append(row)
                            seen.add(key)
                        if len(compact) == 12:
                            break
                    rows = compact
        packed, used = [], 0
        for row in rows:
            # Bounded chunks preserve M0's most recent data instead of dropping an
            # entire long session because it does not fit.
            text = row["text"]
            if estimate_tokens(json.dumps(row, ensure_ascii=False)) > evidence_cap:
                while text and estimate_tokens(text) > evidence_cap // 2:
                    text = text[len(text) // 5 :]
                row = dict(row, text=text)
            n = estimate_tokens(json.dumps(row, ensure_ascii=False))
            if used + n <= evidence_cap:
                packed.append(row)
                used += n
        assert all(r["source_id"] in by_id for r in packed)
        return packed, {
            "estimator": "tiktoken-o200k_base",
            "evidence_estimated_tokens": used,
            "eligible_sources": len(eligible),
        }


def answer(model, question, evidence, *, label, known_at, as_of):
    system = 'Answer using only the supplied eligible evidence. Dates and explicit corrections matter. For a past as_of time, answer the fact valid then, using only knowledge available at known_at. If evidence is missing or inconsistent, abstain. Return JSON {"answer":str,"abstain":bool,"citations":[source_id,...]}. The answer should be the concise exact requested value(s), not an explanation or intermediate arithmetic. Cite every source needed. A source id is not itself evidence. Never invent absent values.'
    user = json.dumps(
        {
            "question": question,
            "known_at": known_at,
            "as_of": as_of,
            "evidence": evidence,
        },
        ensure_ascii=False,
    )
    estimated = estimate_tokens(system + user)
    if estimated > 10000:
        raise ValueError("Whole reader input exceeds the declared estimator budget")
    value, record = model.json(system, user, max_tokens=768, label=label)
    return value, record, estimated
