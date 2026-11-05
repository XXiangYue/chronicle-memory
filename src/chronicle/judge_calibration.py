"""Known positive/negative sanity controls; not independent human validation."""

from pathlib import Path
from .common import ROOT, freeze, write_json, rate, digest
from .memory_data import public_cases
from .public_memory_eval import official_prompt
from .model import Model


def run(out):
    cases = list(public_cases(ROOT / "data/cache/longmemeval_s_cleaned.json"))
    groups = {}
    for c in cases:
        groups.setdefault((c["private"]["type"], c["private"]["answerable"]), c)
    controls = []
    for (typ, answerable), c in sorted(groups.items()):
        for expected in (True, False):
            hypothesis = (
                (
                    c["private"]["answer"]
                    if answerable
                    else "There is insufficient information in my records to answer this question."
                )
                if expected
                else (
                    "The answer is a made-up unrelated value: 271828 purple penguins."
                    if answerable
                    else "Yes, the exact answer is 271828 purple penguins."
                )
            )
            controls.append(
                {
                    "question_id": c["id"],
                    "type": typ,
                    "answerable": answerable,
                    "question": c["question"],
                    "reference": c["private"]["answer"],
                    "hypothesis": hypothesis,
                    "expected": expected,
                }
            )
    freeze(
        out,
        {
            "controls": controls,
            "judge": "deepseek-v4-pro",
            "prompt": "Unmodified official task-specific get_anscheck_prompt",
            "parser": "strict yes/no",
            "scope": "Trivial known-answer sanity controls, no human validation or calibration to downstream public scores",
        },
    )
    if (out / "summary.json").exists():
        return
    judge = Model(model="deepseek-v4-pro")
    fn = official_prompt()
    rows = []
    for i, c in enumerate(controls):
        r = judge.chat(
            [
                {
                    "role": "user",
                    "content": fn(
                        c["type"],
                        c["question"],
                        c["reference"],
                        c["hypothesis"],
                        abstention=not c["answerable"],
                    ),
                }
            ],
            max_tokens=10,
            label=f"P2:judge-calibration:{i}",
        )
        word = (r["message"].get("content") or "").strip().lower().strip(". ")
        rows.append(
            {
                **c,
                "response": word,
                "correct": word == ("yes" if c["expected"] else "no"),
                "usage": r["usage"],
            }
        )
    write_json(
        out / "summary.json",
        {
            "correct": rate(sum(r["correct"] for r in rows), len(rows)),
            "rows": rows,
            "limit": "Known easy controls only; same-family judge, no independent human validation",
        },
    )


if __name__ == "__main__":
    run(ROOT / "evidence/P2/judge_calibration_v1")
