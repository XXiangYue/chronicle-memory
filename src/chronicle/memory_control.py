"""Post-primary equal-row ablation; the main frozen result is never retuned."""

from concurrent.futures import ThreadPoolExecutor
import json
from .common import ROOT, freeze, write_json, append_jsonl, rate, digest, read_jsonl
from .memory import Memory, answer
from .memory_data import build_custom
from .memory_eval import scalar_correct
from .model import Model


def run(out):
    histories = [h for h in build_custom() if h["split"] == "test"]
    freeze(
        out,
        {
            "purpose": "Post-primary diagnostic of equal12-row ordinary retrieval; no tuning of original arms or public benchmark",
            "histories": histories,
            "arm": "M1-12",
            "reader": "deepseek-flash",
            "source": {
                n: digest((ROOT / "src/chronicle" / n).read_bytes())
                for n in (
                    "memory.py",
                    "memory_control.py",
                    "memory_data.py",
                    "memory_eval.py",
                )
            },
        },
    )
    if (out / "summary.json").exists():
        return
    done = {r["id"] for r in read_jsonl(out / "trials.jsonl")}

    def one(h):
        m = Memory(
            ROOT / "evidence/P2/custom_main_v1/stores" / (h["id"] + ".sqlite"), h["id"]
        )
        model = Model()
        for q in h["questions"]:
            if q["id"] in done:
                continue
            ev, _ = m.context(q["question"], "M1", q["known_at"], q["as_of"], "zh")
            ev = ev[:12]
            try:
                value, meta, _ = answer(
                    model,
                    q["question"],
                    ev,
                    label="P2:equal12:" + q["id"],
                    known_at=q["known_at"],
                    as_of=q["as_of"],
                )
                abst = value.get("abstain") is True
                allowed = {e["source_id"] for e in ev}
                cited = set(value.get("citations", []))
                ok = (
                    (
                        abst
                        if not q["answerable"]
                        else not abst
                        and scalar_correct(value.get("answer", ""), q["answer"])
                    )
                    and cited <= allowed
                    and any(
                        set(group) <= cited
                        for group in q.get(
                            "acceptable_source_sets", [q["required_sources"]]
                        )
                    )
                )
                row = {
                    "id": q["id"],
                    "history": h["id"],
                    "success": bool(ok),
                    "answer": value,
                    "usage": meta["usage"],
                    "evidence": ev,
                }
            except Exception as exc:
                row = {
                    "id": q["id"],
                    "success": False,
                    "error_type": type(exc).__name__,
                }
            append_jsonl(out / "trials.jsonl", row)
        print(h["id"], flush=True)

    with ThreadPoolExecutor(3) as pool:
        list(pool.map(one, histories))
    rows = read_jsonl(out / "trials.jsonl")
    write_json(
        out / "summary.json",
        {
            "success": rate(sum(r["success"] for r in rows), len(rows)),
            "input_tokens": sum(
                r.get("usage", {}).get("prompt_tokens", 0) for r in rows
            ),
            "limit": "Additional equal-row control after primary freeze; synthetic template families, no independent user tasks",
        },
    )


if __name__ == "__main__":
    run(ROOT / "evidence/P2/equal12_control_v1")
