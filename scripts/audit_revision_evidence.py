"""Check if the two light arms actually gave the reader different quoted sources.

Replay from cached extraction/routing results only. Never call an inference API.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

from supersede_eval import MODEL, READ, run_episode

from chronicle.common import write_json


class Replay:
    def __init__(self, cache):
        self.cache = cache
        self.evidence = None

    def ask(self, instruction, content, stage):
        if instruction == READ:
            self.evidence = content["evidence"]
            return {"answer": "audit"}
        body = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(content, ensure_ascii=False)},
            ],
            "temperature": 0,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": 400,
        }
        name = hashlib.sha256(json.dumps(body).encode()).hexdigest()
        return json.loads((self.cache / (name + ".json")).read_bytes())["result"]


def run(data, cache):
    result = []
    for row in map(json.loads, data.read_text().splitlines()):
        controls = []
        for arm in ("latest", "chronicle"):
            calls = Replay(cache)
            run_episode(row["sessions"], row["question"], arm, calls)
            controls.append(calls.evidence)
        before, after = controls
        normalized = [re.sub(r"^Session [0-9]+: ", "", x, count=1) for x in after]
        result.append(
            {
                "qid": row["qid"],
                "same_source_quotes": before == normalized,
                "identical_reader_evidence": before == after,
            }
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("data", "cache", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    records = run(args.data, args.cache)
    write_json(
        args.output,
        {
            "rows": records,
            "same_source_quotes": sum(r["same_source_quotes"] for r in records),
            "identical_reader_evidence": sum(
                r["identical_reader_evidence"] for r in records
            ),
        },
    )
