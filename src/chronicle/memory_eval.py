from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re
import time

from .common import (
    ROOT,
    append_jsonl,
    digest,
    freeze,
    percentile,
    rate,
    read_jsonl,
    write_json,
)
from .memory import Memory, answer, embedding
from .memory_data import build_custom, public_cases
from .model import Model


def normalized(value):
    return re.sub(r"\s+", "", str(value)).lower().strip("。.!！")


def scalar_correct(actual, expected):
    if isinstance(expected, list):
        return all(normalized(x) in normalized(actual) for x in expected)
    expected = str(expected)
    if expected.isdigit():
        # Exact answer value with a permitted unit, not any matching intermediate
        # number in a derivation or a substring of a different number.
        return (
            re.fullmatch(re.escape(expected) + r"(?:元|次)?", normalized(actual))
            is not None
        )
    return normalized(actual) == normalized(expected)


def summarize_custom(records):
    result = {}
    for arm in ("M0", "M1", "M2"):
        rows = [r for r in records if r["arm"] == arm]
        ans = [r for r in rows if r["answerable"]]
        una = [r for r in rows if not r["answerable"]]
        result[arm] = {
            "n": len(rows),
            "answer_correct": rate(
                sum(r.get("answer_correct", False) for r in rows), len(rows)
            ),
            "all_conditions_success": rate(
                sum(r.get("success", False) for r in rows), len(rows)
            ),
            "false_refusal": rate(sum(r.get("abstain", True) for r in ans), len(ans)),
            "false_answer_unanswerable": rate(
                sum(not r.get("abstain", True) for r in una), len(una)
            ),
            "reader_input_tokens": sum(
                r.get("usage", {}).get("prompt_tokens", 0) for r in rows
            ),
            "query_p95_ms": percentile([r["query_ms"] for r in rows], 0.95),
            "by_category": {
                c: rate(
                    sum(r.get("success", False) for r in rows if r["category"] == c),
                    sum(r["category"] == c for r in rows),
                )
                for c in sorted({r["category"] for r in rows})
            },
        }
    return result


def evaluate_custom(out: Path, *, split="dev", histories_limit=None, workers=2):
    histories = [h for h in build_custom() if h["split"] == split]
    if histories_limit:
        histories = histories[:histories_limit]
    setup_started = time.perf_counter()
    embedding(["模型预热，不包含任务数据"], "zh")
    setup_ms = (time.perf_counter() - setup_started) * 1000
    protocol = {
        "project": "P2",
        "split": split,
        "histories": [h["id"] for h in histories],
        "dataset_sha256": digest(histories),
        "arms": ["M0", "M1", "M2"],
        "reader": "deepseek-flash",
        "note_extractor": "deepseek-flash",
        "evidence_estimator": "tiktoken-o200k_base",
        "evidence_estimated_token_cap": 8192,
        "reader_estimated_input_cap": 10000,
        "primary": "final answer/citation success and context usage; M1-to-M2 compression selected on development only, no promised accuracy gain",
        "shared_hard_controls": "namespace, observed_at<=known_at, deletion; dependent notes cannot predate their derivation input",
        "code_sha256": {
            p.name: digest(p.read_bytes())
            for p in [
                Path(__file__),
                Path(__file__).with_name("memory.py"),
                Path(__file__).with_name("memory_data.py"),
                Path(__file__).with_name("model.py"),
                Path(__file__).with_name("common.py"),
            ]
        },
    }
    freeze(out, protocol)
    if (out / "summary.json").exists():
        return json.loads((out / "summary.json").read_text())
    write_json(
        out / "setup.json",
        {
            "warmup_ms": setup_ms,
            "embedding_cache": "separate cache namespace per comparison arm; model warmup shared outside query timing",
        },
    )
    write_json(out / "private_dataset.json", histories)
    model = Model()
    path = out / "trials.jsonl"
    finished = {(r["id"], r["arm"]) for r in read_jsonl(path)}

    def run_history(h):
        memory = Memory(out / "stores" / (h["id"] + ".sqlite"), h["id"])
        memory.ingest(h["sources"])
        ingest_path = out / "ingestion" / (h["id"] + ".json")
        if not ingest_path.exists():
            try:
                extracted = memory.extract(model)
                write_json(ingest_path, extracted)
            except Exception as exc:
                write_json(
                    ingest_path,
                    {
                        "error_type": type(exc).__name__,
                        "status": "failed_no_oracle_fallback",
                    },
                )
        for q in h["questions"]:
            for arm in ("M0", "M1", "M2"):
                if (q["id"], arm) in finished:
                    continue
                t = time.perf_counter()
                row = {
                    "id": q["id"],
                    "history": h["id"],
                    "arm": arm,
                    "category": q["category"],
                    "answerable": q["answerable"],
                    "origin": h["origin"],
                }
                try:
                    evidence, context_info = memory.context(
                        q["question"], arm, q["known_at"], q["as_of"], h["language"]
                    )
                    reply, meta, estimated = answer(
                        model,
                        q["question"],
                        evidence,
                        label=f"P2:{split}:{q['id']}:{arm}",
                        known_at=q["known_at"],
                        as_of=q["as_of"],
                    )
                    abstain = reply.get("abstain") is True
                    value_ok = (
                        abstain
                        if not q["answerable"]
                        else not abstain
                        and scalar_correct(reply.get("answer", ""), q["answer"])
                    )
                    allowed = {e["source_id"] for e in evidence}
                    cited = set(reply.get("citations", []))
                    citations_eligible = cited <= allowed
                    coverage = any(
                        set(group) <= cited
                        for group in q.get(
                            "acceptable_source_sets", [q["required_sources"]]
                        )
                    )
                    row.update(
                        status="completed",
                        answer=reply,
                        abstain=abstain,
                        answer_correct=bool(value_ok),
                        citations_eligible=citations_eligible,
                        required_citation_coverage=coverage,
                        success=bool(value_ok and citations_eligible and coverage),
                        evidence=evidence,
                        context=context_info,
                        estimated_reader_input_tokens=estimated,
                        usage=meta["usage"],
                        actual_model=meta["model"],
                        fingerprint=meta["fingerprint"],
                        cost_upper_bound_usd=meta["cost_upper_bound_usd"],
                    )
                except Exception as exc:
                    row.update(
                        status="error",
                        error_type=type(exc).__name__,
                        answer_correct=False,
                        success=False,
                        abstain=True,
                    )
                row["query_ms"] = (time.perf_counter() - t) * 1000
                append_jsonl(path, row)
        return h["id"]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(run_history, h) for h in histories]):
            print("completed", future.result(), flush=True)
    rows = read_jsonl(path)
    summary = summarize_custom(rows)
    summary["coverage"] = {
        "requested": len(histories) * 12 * 3,
        "recorded": len(rows),
        "errors": sum(r["status"] != "completed" for r in rows),
    }
    summary["scope"] = (
        "Synthetic history-level split; shared hard eligibility; deterministic answer/citation labels; not real-user adoption."
    )
    write_json(out / "summary.json", summary)
    return summary
