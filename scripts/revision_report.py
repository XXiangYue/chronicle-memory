"""Export compact measurements and recompute paired scores without model calls."""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np

from chronicle.common import write_json

ARMS = ("latest", "chronicle", "graphiti")
FIELDS = ("write", "route", "reader", "fallback_reader", "judge")


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def dump_rows(path, records):
    path.write_text(
        "".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records
        )
    )


def compact(raw):
    stages = {}
    for call in raw["calls"]:
        stage = call["stage"].removeprefix("graph_")
        entry = stages.setdefault(stage, {"calls": 0, "input": 0, "output": 0})
        entry["calls"] += 1
        entry["input"] += call["prompt"]
        entry["output"] += call["completion"]
    return stages


def cache_usage(folder):
    totals = Counter()
    for p in (folder / "calls").glob("*.json"):
        record = json.loads(p.read_bytes())
        u = record["usage"]
        totals.update(
            {
                "requests": 1,
                "input": u["prompt_tokens"],
                "output": u["completion_tokens"],
                "cache_hit_input": u.get("prompt_cache_hit_tokens", 0),
                "recorded_invalid_json": int("error" in record),
            }
        )
    return dict(totals)


def export(args):
    dest = args.output
    dest.mkdir(exist_ok=True, parents=True)
    inputs = rows(args.data)
    episodes = []
    for source in inputs:
        qid = source["qid"]
        for arm in ARMS:
            path = args.test / (qid + "__" + arm + ".json")
            if not path.exists():
                episodes.append(
                    {
                        "qid": qid,
                        "arm": arm,
                        "n_sessions": source["n_sessions"],
                        "status": "missing",
                    }
                )
                continue
            raw = json.loads(path.read_bytes())
            if (
                raw["qid"] != qid
                or raw["arm"] != arm
                or raw["n_sessions"] != source["n_sessions"]
            ):
                raise ValueError(f"Trial identity mismatch for {qid} {arm}")
            item = {
                k: raw[k]
                for k in ("qid", "arm", "n_sessions", "answer", "correct", "stale")
            }
            item.update(status="completed", stages=compact(raw))
            if "embedding" in raw:
                embeds = raw["embedding"]
                item["embedding"] = {
                    "requests": len(embeds),
                    "vectors": sum(x["n"] for x in embeds),
                    "reported_tokens": sum(x["tokens"] or 0 for x in embeds),
                    "unmetered_requests": sum(x["tokens"] is None for x in embeds),
                    "summed_request_seconds": round(
                        sum(x["seconds"] for x in embeds), 6
                    ),
                    "episode_wall_seconds": round(raw["elapsed"], 6),
                }
            episodes.append(item)
    dump_rows(dest / "supersede.jsonl", episodes)
    transfer = []
    known = set()
    for file in sorted(args.transfer.glob("*.json")):
        r = json.loads(file.read_bytes())
        transfer.append(
            {
                "qid": r["qid"],
                "answerable": r["answerable"],
                "correct": r["correct"],
                "status": "completed",
                "answer_sha256": hashlib.sha256(str(r["answer"]).encode()).hexdigest(),
                "stages": compact(r),
            }
        )
        known.add(r["qid"])
    for file in sorted((args.transfer / "errors").glob("*.json")):
        r = json.loads(file.read_bytes())
        if r["qid"] not in known:
            transfer.append(
                {
                    "qid": r["qid"],
                    "answerable": r["answerable"],
                    "status": "execution_error",
                    "error_class": r["error"],
                    "failed_stage": r["stage"],
                    "stages": compact(r),
                }
            )
    dump_rows(dest / "longmemeval.jsonl", sorted(transfer, key=lambda r: r["qid"]))
    with sqlite3.connect(
        f"file:{args.test / 'graph-budget.sqlite'}?mode=ro", uri=True
    ) as con:
        con.row_factory = sqlite3.Row
        ledger = [
            dict(row)
            for row in con.execute("""SELECT label AS qid,status,COUNT(*) AS requests,
            SUM(input_tokens) AS input,SUM(output_tokens) AS output,
            ROUND(SUM(CASE WHEN status='reserved' THEN reserved ELSE cost END),8) AS normalized_upper_usd
            FROM calls GROUP BY label,status ORDER BY label,status""")
        ]
    dump_rows(dest / "graphiti_write_attempts.jsonl", ledger)
    write_json(
        dest / "usage.json",
        {
            "test_shared_extractor_router_reader_cache": cache_usage(args.test),
            "transfer_shared_cache": cache_usage(args.transfer),
            "graph_ledger": "See graphiti_write_attempts.jsonl. Includes retries, uncertain charges and abandoned reservations.",
            "limits": "Uniquely saved logical request payloads are counted once per cache. Response caching reuses repeated templates and shared controls. Model invoices and usage for initial transfer malformed responses without cached metadata are unavailable. Local embedding time on interrupted attempts was not saved.",
        },
    )


def sum_stages(records):
    result = {}
    for stage in FIELDS:
        events = [r["stages"][stage] for r in records if stage in r.get("stages", {})]
        if events:
            result[stage] = {
                k: sum(x[k] for x in events) for k in ("calls", "input", "output")
            }
    return result


def tokens(stages):
    return sum(s["input"] + s["output"] for s in stages.values())


def stat(records):
    valid = [r for r in records if r["status"] == "completed"]
    stages = sum_stages(records)
    result = {
        "requested": len(records),
        "completed": len(valid),
        "sessions_completed": sum(r["n_sessions"] for r in valid),
        "current_correct": sum(r["correct"] for r in valid),
        "used_stale": sum(r["stale"] for r in valid),
        "stages": stages,
        "logical_total_lm_tokens": tokens(stages),
    }
    write = stages.get("write", {})
    if valid:
        result["write_lm_tokens_per_100_sessions"] = round(
            100
            * (write.get("input", 0) + write.get("output", 0))
            / result["sessions_completed"],
            2,
        )
    embed = [r["embedding"] for r in valid if "embedding" in r]
    if embed:
        result["embedding"] = {k: round(sum(x[k] for x in embed), 6) for k in embed[0]}
    return result


def comparison(first, second):
    """Each resample draws matched episodes, preserving both systems' decisions."""
    paired = sorted(first.keys() & second.keys())
    diff = np.array(
        [
            [int(first[k][s]) - int(second[k][s]) for s in ("correct", "stale")]
            for k in paired
        ],
        dtype=int,
    )
    rng = np.random.default_rng(20261105)
    draws = 100 * diff[rng.integers(0, len(paired), size=(10000, len(paired)))].mean(
        axis=1
    )
    out = {"paired": len(paired)}
    for i, s in enumerate(("correct", "stale")):
        out[s] = {
            "first_only": int((diff[:, i] > 0).sum()),
            "second_only": int((diff[:, i] < 0).sum()),
            "first_minus_second_pp": round(float(diff[:, i].mean()) * 100, 3),
            "paired_percentile95_pp": np.round(
                np.quantile(draws[:, i], [0.025, 0.975]), 3
            ).tolist(),
        }
    return out


def summary(directory):
    episode_rows = rows(directory / "supersede.jsonl")
    arm_groups = {a: [r for r in episode_rows if r["arm"] == a] for a in ARMS}
    if any(
        len({r["qid"] for r in group}) != len(group) for group in arm_groups.values()
    ):
        raise ValueError("Duplicate episode id")
    if len({frozenset(r["qid"] for r in g) for g in arm_groups.values()}) != 1:
        raise ValueError("Arm input identities differ")
    stat_by_arm = {a: stat(group) for a, group in arm_groups.items()}
    valid = {
        a: {r["qid"]: r for r in group if r["status"] == "completed"}
        for a, group in arm_groups.items()
    }
    paired = {
        arm: comparison(valid["chronicle"], valid[arm])
        for arm in ("graphiti", "latest")
        if valid[arm]
    }
    transfer = rows(directory / "longmemeval.jsonl")
    transfer_result = {}
    for name, flag in (("answerable", True), ("abstention", False)):
        group = [r for r in transfer if r["answerable"] == flag]
        transfer_result[name] = {
            "attempted": len(group),
            "correct": sum(r.get("correct", False) for r in group),
            "execution_errors": sum(r["status"] != "completed" for r in group),
            "stages": sum_stages(group),
        }
    return {
        "arms": stat_by_arm,
        "chronicle_minus_comparator": paired,
        "transfer": transfer_result,
    }


def main():
    parser = argparse.ArgumentParser()
    cmd = parser.add_subparsers(dest="action", required=True)
    exp = cmd.add_parser("export")
    for name in ("data", "test", "transfer", "output"):
        exp.add_argument(name, type=Path)
    score = cmd.add_parser("rescore")
    for name in ("output", "data", "reward"):
        score.add_argument(name, type=Path)
    for name in ("summarize", "verify"):
        sub = cmd.add_parser(name)
        sub.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.action == "rescore":
        from supersede_eval import load_reward

        truth = {r["qid"]: r for r in rows(args.data)}
        scorer = load_reward(args.reward)
        count = 0
        for r in rows(args.output / "supersede.jsonl"):
            if r["status"] != "completed":
                continue
            source = truth[r["qid"]]
            observed = (
                bool(scorer.answer_matches(r["answer"], source["answer"])),
                bool(scorer.stale_use_penalty(r["answer"], source["stale_values"])),
            )
            if observed != (r["correct"], r["stale"]):
                raise ValueError(f"Score mismatch for {r['qid']} ({r['arm']})")
            count += 1
        print(f"Verified official scorer labels on {count} completed answers.")
        return
    if args.action == "export":
        export(args)
    report = summary(args.output)
    file = args.output / "summary.json"
    if args.action == "verify":
        if json.loads(file.read_bytes()) != report:
            raise ValueError("Published summary differs from per-trial records")
        print("Verified paired outcomes, token accounting and transfer denominators.")
    else:
        write_json(file, report)


if __name__ == "__main__":
    main()
