"""Run isolated Supersede episodes and resume only missing Graphiti outputs."""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from chronicle.common import write_json


def main():
    parser = argparse.ArgumentParser()
    for name in ("data", "out", "reward"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.workers < 1 or args.attempts < 1:
        parser.error("workers and attempts must be positive")
    args.out.mkdir(exist_ok=True, parents=True)
    logs = args.out / "logs"
    logs.mkdir(exist_ok=True)
    records = [json.loads(line) for line in args.data.read_text().splitlines()][
        : args.limit
    ]
    env = dict(os.environ, GRAPHITI_TELEMETRY_ENABLED="false")

    def one(index):
        qid = records[index]["qid"]
        if not qid.replace("_", "").isalnum():
            raise ValueError("Invalid input id")
        target = args.out / (qid + "__graphiti.json")
        if target.exists():
            return True
        command = [
            sys.executable,
            str(Path(__file__).with_name("graphiti_arm.py")),
            str(args.data),
            str(args.out),
            str(args.reward),
            "--offset",
            str(index),
            "--limit",
            "1",
        ]
        for _ in range(args.attempts):
            with (logs / (qid + ".log")).open("ab") as log:
                try:
                    result = subprocess.run(
                        command,
                        env=env,
                        timeout=360,
                        stdout=log,
                        stderr=log,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    continue
                if result.returncode == 0 and target.is_file():
                    return True
        return False

    with ThreadPoolExecutor(args.workers) as pool:
        completed = list(pool.map(one, range(len(records))))
    missing = [r["qid"] for r, ok in zip(records, completed, strict=True) if not ok]
    write_json(
        args.out / "logs" / "coverage.json",
        {"requested": len(records), "completed": sum(completed), "missing": missing},
    )
    print(f"Completed {sum(completed)} / {len(records)}; missing {len(missing)}")
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
