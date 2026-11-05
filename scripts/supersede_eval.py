"""Run current-value QA without exposing evaluation labels to the memory systems."""

import argparse
import hashlib
import importlib.util
import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib import request

from chronicle.common import write_json
from chronicle.revisions import Timeline

MODEL = "deepseek-flash"
EXTRACT = """Extract explicitly stated personal facts from the user's speech only. Return JSON {"facts":[{"owner":"user" or named subject,"attribute":canonical field,"value":string,"kind":"standing" or "temporary" or "uncertain","quote":verbatim user substring}]}. Use city, employer, car, pet, budget, preference or address for those concepts, or a short lowercase field name. A standing revision changes the enduring fact. A trip or a hypothetical possibility is not a relocation. Generic chatter needs no record. Do not infer missing values."""
READ = 'Answer the question only from the supplied evidence. Do not confuse a temporary exception with the current standing fact. Return JSON {"answer":"short current value or unknown"}.'
LOCKS = [threading.Lock() for _ in range(64)]


class Calls:
    def __init__(self, cache, *, transfer_repair=False):
        self.cache = cache
        self.events = []
        self.transfer_repair = transfer_repair

    def ask(self, instruction, content, stage):
        # Only the transfer run enables transport repair. Supersede keeps its
        # preregistered output limit and request/cache identity.
        limits = (400, 1200, 3600, 7200) if self.transfer_repair else (400,)
        for limit in limits:
            body = {
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": instruction},
                    {
                        "role": "user",
                        "content": json.dumps(content, ensure_ascii=False),
                    },
                ],
                "temperature": 0,
                "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"},
                "max_tokens": limit,
            }
            raw = json.dumps(body).encode()
            key = hashlib.sha256(raw).hexdigest()
            path = self.cache / (key + ".json")
            with LOCKS[int(key[:6], 16) % len(LOCKS)]:
                if not path.exists():
                    req = request.Request(
                        os.environ["OUTCOMES_API_BASE"].rstrip("/")
                        + "/chat/completions",
                        data=raw,
                        headers={
                            "Authorization": "Bearer " + os.environ["OUTCOMES_API_KEY"],
                            "Content-Type": "application/json",
                        },
                    )
                    with request.urlopen(req, timeout=90) as response:
                        reply = json.load(response)
                    choice = reply["choices"][0]
                    record = {
                        "usage": reply["usage"],
                        "finish_reason": choice.get("finish_reason"),
                    }
                    try:
                        record["result"] = json.loads(choice["message"]["content"])
                    except (ValueError, TypeError):
                        record["error"] = "invalid_json"
                    with tempfile.NamedTemporaryFile(
                        mode="w", dir=self.cache, delete=False
                    ) as f:
                        json.dump(record, f)
                    Path(f.name).replace(path)
                record = json.loads(path.read_text())
            usage = record["usage"]
            self.events.append(
                {
                    "stage": stage,
                    "call": key,
                    "prompt": usage["prompt_tokens"],
                    "completion": usage["completion_tokens"],
                    "valid_json": "result" in record,
                }
            )
            if isinstance(record.get("result"), dict):
                return record["result"]
        raise ValueError(f"Invalid JSON after {len(limits)} attempts in {stage}")


def run_episode(sessions, question, arm, calls):
    timeline = Timeline()
    for i, text in enumerate(sessions):
        facts = calls.ask(EXTRACT, text, "write").get("facts", [])
        timeline.append(i, text, facts)
    slot = calls.ask(
        'Map the question to a subject (use user for first person) and a canonical fact field. Use city, employer, car, pet, budget, preference or address for those concepts, otherwise a short lowercase field. Return JSON {"owner":"...", "attribute":"..."}.',
        question,
        "route",
    )
    owner, attribute = slot["owner"], slot["attribute"]
    if arm == "latest":
        relevant = [
            r for r in timeline.entries if (r.owner, r.attribute) == (owner, attribute)
        ]
        evidence = [max(relevant, key=lambda r: r.sequence).source] if relevant else []
    else:
        evidence = timeline.evidence(owner, attribute)
    if not evidence and arm == "chronicle":
        evidence = sessions[-3:]
        stage = "fallback_reader"
    else:
        stage = "reader"
    return calls.ask(READ, {"evidence": evidence, "question": question}, stage)[
        "answer"
    ]


def load_reward(path):
    if (
        hashlib.sha256(path.read_bytes()).hexdigest()
        != "3cc03c858613a3055a67c4d019d61990258bdd492f49a1ff96d44c3f5ea8a249"
    ):
        raise ValueError("Unexpected Supersede scoring implementation")
    source = importlib.util.spec_from_file_location("official_reward", path)
    scorer = importlib.util.module_from_spec(source)
    source.loader.exec_module(scorer)
    return scorer


def main():
    p = argparse.ArgumentParser()
    p.add_argument("data", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("reward", type=Path)
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=8)
    args = p.parse_args()
    scorer = load_reward(args.reward)
    cache = args.out / "calls"
    cache.mkdir(exist_ok=True, parents=True)
    rows = [json.loads(l) for l in args.data.open()][: args.limit]

    def one(r):
        for arm in ("latest", "chronicle"):
            path = args.out / (r["qid"] + "__" + arm + ".json")
            if path.exists():
                continue
            calls = Calls(cache)
            try:
                ans = run_episode(r["sessions"], r["question"], arm, calls)
                result = {
                    "qid": r["qid"],
                    "arm": arm,
                    "n_sessions": r["n_sessions"],
                    "answer": ans,
                    "correct": bool(scorer.answer_matches(ans, r["answer"])),
                    "stale": bool(scorer.stale_use_penalty(ans, r["stale_values"])),
                    "calls": calls.events,
                }
                write_json(path, result)
            except (OSError, KeyError, TypeError, ValueError) as e:
                write_json(
                    args.out / "errors" / path.name,
                    {
                        "qid": r["qid"],
                        "arm": arm,
                        "error": type(e).__name__,
                        "calls": calls.events,
                    },
                )
                print(
                    r["qid"], arm, type(e).__name__, getattr(e, "code", ""), flush=True
                )

    with ThreadPoolExecutor(args.workers) as e:
        list(e.map(one, rows))


if __name__ == "__main__":
    main()
