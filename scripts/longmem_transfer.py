"""Frozen transfer of the current-value policy to LongMemEval knowledge updates."""

import argparse
import ast
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from supersede_eval import Calls, run_episode

from chronicle.common import write_json


def judge_function(path):
    if (
        hashlib.sha256(path.read_bytes()).hexdigest()
        != "fd5795d42fd70a109c3a93deaa4af0aeb381fea6ff90b7023d47ab8b885dec77"
    ):
        raise ValueError("Unexpected LongMemEval judging implementation")
    module = ast.parse(path.read_text())
    fn = next(
        n
        for n in module.body
        if isinstance(n, ast.FunctionDef) and n.name == "get_anscheck_prompt"
    )
    scope = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), scope)  # noqa: S102 -- fixed, hashed upstream rubric
    return scope[fn.name]


def main():
    p = argparse.ArgumentParser()
    for k in ("dataset", "out", "official"):
        p.add_argument(k, type=Path)
    a = p.parse_args()
    cache = a.out / "calls"
    cache.mkdir(exist_ok=True, parents=True)
    rubric = judge_function(a.official)
    rows = [
        r
        for r in json.loads(a.dataset.read_bytes())
        if r["question_type"] == "knowledge-update"
    ]

    def one(row):
        qid = row["question_id"]
        out = a.out / (qid + ".json")
        if out.exists():
            return
        turns = sorted(
            zip(
                row["haystack_dates"],
                range(len(row["haystack_sessions"])),
                row["haystack_sessions"],
            )
        )
        sessions = [
            "\n".join("user: " + t["content"] for t in chat if t["role"] == "user")
            for _, _, chat in turns
        ]
        calls = Calls(cache, transfer_repair=True)
        try:
            ans = run_episode(sessions, row["question"], "chronicle", calls)
            prompt = rubric(
                row["question_type"],
                row["question"],
                row["answer"],
                ans,
                abstention=qid.endswith("_abs"),
            )
            verdict = (
                calls.ask(
                    'Apply the supplied LongMemEval official rubric; return JSON {"label":"yes" or "no"}.',
                    prompt,
                    "judge",
                )["label"]
                .lower()
                .strip()
            )
            if verdict not in ("yes", "no"):
                raise ValueError("invalid judgment")
            write_json(
                out,
                {
                    "qid": qid,
                    "answer": ans,
                    "correct": verdict == "yes",
                    "answerable": not qid.endswith("_abs"),
                    "calls": calls.events,
                },
            )
        except (OSError, TypeError, ValueError, KeyError) as exc:
            write_json(
                a.out / "errors" / (qid + ".json"),
                {
                    "qid": qid,
                    "error": type(exc).__name__,
                    "stage": calls.events[-1]["stage"] if calls.events else "init",
                    "calls": calls.events,
                    "answerable": not qid.endswith("_abs"),
                },
            )
            print(qid, type(exc).__name__, getattr(exc, "code", ""), flush=True)

    with ThreadPoolExecutor(16) as e:
        list(e.map(one, rows))


if __name__ == "__main__":
    main()
