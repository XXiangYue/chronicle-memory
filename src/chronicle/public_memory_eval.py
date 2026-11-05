"""Full cleaned LongMemEval evaluation with isolated gold and fixed judge prompt."""

from __future__ import annotations
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time

from .common import ROOT, append_jsonl, digest, freeze, rate, read_jsonl, write_json
from .memory import Memory, answer, embedding
from .memory_data import public_cases
from .model import Model


def official_prompt():
    path = ROOT / "upstream/longmemeval_evaluate_qa.py"
    tree = ast.parse(path.read_text())
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "get_anscheck_prompt"
    )
    namespace = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["get_anscheck_prompt"]


def evaluate_public(out: Path, *, limit=None, workers=4, score=True):
    source = ROOT / "data/cache/longmemeval_s_cleaned.json"
    cases = list(public_cases(source))
    if limit:
        # Resource-only probe covers types without using answer labels or scores.
        groups = {}
        for c in cases:
            groups.setdefault(c["private"]["type"], []).append(c)
        selected = []
        while len(selected) < limit:
            for key in sorted(groups):
                if groups[key] and len(selected) < limit:
                    selected.append(groups[key].pop(0))
        cases = selected
    warm = time.perf_counter()
    embedding(["model warmup only"], "en")
    warm_ms = (time.perf_counter() - warm) * 1000
    protocol = {
        "project": "P2",
        "dataset": "LongMemEval-S cleaned",
        "dataset_sha256": digest(source.read_bytes()),
        "requested_questions": len(cases),
        "question_ids": [c["id"] for c in cases],
        "arms": ["M0", "M1", "M2"],
        "reader": "deepseek-flash",
        "extractor": "deepseek-flash",
        "judge": "deepseek-v4-pro" if score else None,
        "judge_prompt": "Official get_anscheck_prompt; strict yes/no parsing instead of substring match",
        "public_score_scope": "Custom reader/judge configuration; not an official leaderboard submission or directly interchangeable with GPT-4o judge scores.",
        "evidence_estimated_token_cap": 8192,
        "total_reader_estimated_input_cap": 10000,
        "estimator": "tiktoken-o200k_base",
        "embedding": "BAAI/bge-small-en-v1.5",
        "cache": "separate per-arm text embedding caches; shared model warmup excluded from query timing",
        "primary": "QA correctness using official task-specific prompt, model judge, failures visible",
        "reference_diagnostics": "Gold session overlap is diagnostic, not required for the official-style QA label",
        "cost_policy": "Shared global75USD peak-equivalent conservative bound; ingestion/reader/judge/retries all charged. Public ingestion budget revised from provisional25M based on actual downloaded277MB corpus before answer scoring.",
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
        {"model_warmup_ms": warm_ms, "resource_probe_without_scoring": not score},
    )
    model = Model()
    judge = Model(model="deepseek-v4-pro") if score else None
    prompt_fn = official_prompt()
    path = out / "trials.jsonl"
    done = {(r["question_id"], r["arm"]) for r in read_jsonl(path)}

    def run_case(case):
        qid = case["id"]
        private = case["private"]
        source_origins = {
            s["id"]: s.get("origin_session_id", s["id"]) for s in case["sources"]
        }
        memory = Memory(out / "stores" / (digest(qid) + ".sqlite"), "public:" + qid)
        memory.ingest(case["sources"])
        ing_path = out / "ingestion" / (digest(qid) + ".json")
        if not ing_path.exists():
            try:
                write_json(ing_path, memory.extract(model, max_tokens=4096))
            except Exception as exc:
                write_json(
                    ing_path,
                    {
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "fallback": "ordinary eligible retrieval; no gold notes",
                    },
                )
        for arm in ("M0", "M1", "M2"):
            if (qid, arm) in done:
                continue
            t = time.perf_counter()
            row = {
                "question_id": qid,
                "arm": arm,
                "type": private["type"],
                "answerable": private["answerable"],
            }
            try:
                evidence, info = memory.context(
                    case["question"], arm, case["date"], case["date"], "en"
                )
                reply, meta, estimated = answer(
                    model,
                    case["question"],
                    evidence,
                    label=f"P2:public:{qid}:{arm}",
                    known_at=case["date"],
                    as_of=case["date"],
                )
                hypothesis = reply.get("answer") or (
                    "I do not have enough information to answer."
                    if reply.get("abstain")
                    else ""
                )
                row.update(
                    status="completed",
                    hypothesis=hypothesis,
                    abstain=reply.get("abstain") is True,
                    citations=reply.get("citations", []),
                    evidence=evidence,
                    context=info,
                    usage=meta["usage"],
                    model=meta["model"],
                    fingerprint=meta["fingerprint"],
                    reader_estimated_tokens=estimated,
                    reader_cost_upper_bound_usd=meta["cost_upper_bound_usd"],
                    reference_session_hit=bool(
                        set(private["evidence_sessions"])
                        & {source_origins[e["source_id"]] for e in evidence}
                    ),
                )
                row["query_ms"] = (time.perf_counter() - t) * 1000
                if score:
                    prompt = prompt_fn(
                        private["type"],
                        case["question"],
                        private["answer"],
                        hypothesis,
                        abstention=not private["answerable"],
                    )
                    decision = judge.chat(
                        [{"role": "user", "content": prompt}],
                        max_tokens=10,
                        label=f"P2:public:{qid}:{arm}:judge",
                    )
                    word = (
                        (decision["message"].get("content") or "")
                        .strip()
                        .lower()
                        .strip(". ")
                    )
                    row.update(
                        judge_status="ok" if word in ("yes", "no") else "unparsable",
                        autoeval_label=word == "yes",
                        judge_model=decision["model"],
                        judge_usage=decision["usage"],
                    )
                else:
                    row.update(
                        judge_status="not_run_resource_probe", autoeval_label=None
                    )
            except Exception as exc:
                row.update(
                    status="error",
                    error_type=type(exc).__name__,
                    autoeval_label=False if score else None,
                )
                row.setdefault("query_ms", (time.perf_counter() - t) * 1000)
            append_jsonl(path, row)
        return qid

    count = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(run_case, c) for c in cases]):
            future.result()
            count += 1
            if count % 10 == 0:
                print("public histories completed", count, "/", len(cases), flush=True)
    rows = read_jsonl(path)
    summary = {}
    for arm in ("M0", "M1", "M2"):
        selected = [r for r in rows if r["arm"] == arm]
        summary[arm] = {
            "recorded": len(selected),
            "qa_accuracy": rate(
                sum(r.get("autoeval_label") is True for r in selected), len(selected)
            )
            if score
            else None,
            "judge_coverage": rate(
                sum(r.get("judge_status") == "ok" for r in selected), len(selected)
            ),
            "errors": sum(r["status"] != "completed" for r in selected),
            "reader_input_tokens": sum(
                r.get("usage", {}).get("prompt_tokens", 0) for r in selected
            ),
            "by_type": {
                typ: rate(
                    sum(
                        r.get("autoeval_label") is True
                        for r in selected
                        if r["type"] == typ
                    ),
                    sum(r["type"] == typ for r in selected),
                )
                for typ in sorted({r["type"] for r in selected})
            }
            if score
            else None,
        }
    summary["coverage"] = {
        "requested_trials": len(cases) * 3,
        "recorded_trials": len(rows),
        "full_500_question_run": len(cases) == 500 and len(rows) == 1500,
        "resource_probe": not score,
    }
    summary["limit"] = (
        "Model-judged QA with official prompts and a same-family different judge model; no human truth validation. Gold and has_answer never supplied to ingestion/reader."
    )
    write_json(out / "summary.json", summary)
    return summary
