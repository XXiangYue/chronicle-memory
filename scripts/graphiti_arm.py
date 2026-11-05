"""Isolated Graphiti/Kuzu reference arm for chronological Supersede updates."""

import argparse
import asyncio
import datetime as dt
import json
import os
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch

import httpx
import kuzu
from graphiti_core import Graphiti
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.driver.kuzu_driver import KuzuDriver
from graphiti_core.embedder.client import EmbedderClient
from graphiti_core.graph_queries import get_fulltext_indices
from graphiti_core.llm_client import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.nodes import EpisodeType
from openai import AsyncOpenAI
from supersede_eval import MODEL, READ, Calls, load_reward

from chronicle.common import Budget, write_json


class LocalBGE(EmbedderClient):
    def __init__(self):
        self.stats = []

    async def create_batch(self, input_data_list):
        start = time.monotonic()
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/embed",
            data=json.dumps({"model": "bge-m3", "input": input_data_list}).encode(),
            headers={"Content-Type": "application/json"},
        )

        def send():
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)

        r = await asyncio.to_thread(send)
        self.stats.append(
            {
                "n": len(input_data_list),
                "tokens": r.get("prompt_eval_count"),
                "seconds": time.monotonic() - start,
            }
        )
        return r["embeddings"]

    async def create(self, input_data):
        return (
            await self.create_batch(
                [input_data if isinstance(input_data, str) else " ".join(input_data)]
            )
        )[0]


class NoCrossEncoder(CrossEncoderClient):
    async def rank(self, query, passages):
        raise RuntimeError(
            "The frozen Graphiti hybrid RRF configuration does not invoke a cross encoder"
        )


async def run(row, out, scorer):
    events = []

    async def meter(resp):
        await resp.aread()
        if resp.status_code == 200:
            usage = resp.json()["usage"]
            events.append(
                {
                    "stage": "graph_write",
                    "prompt": usage["prompt_tokens"],
                    "completion": usage["completion_tokens"],
                }
            )

    client = httpx.AsyncClient(event_hooks={"response": [meter]}, timeout=80)
    sdk = AsyncOpenAI(
        api_key=os.environ["OUTCOMES_API_KEY"],
        base_url=os.environ["OUTCOMES_API_BASE"],
        http_client=client,
        max_retries=0,
    )
    ledger = Budget(out / "graph-budget.sqlite", limit_usd=30)
    create = sdk.chat.completions.create

    async def bounded_create(**kwargs):
        if len(events) >= 32 * len(row["sessions"]):
            raise RuntimeError("Graphiti trial call budget reached")
        kwargs["max_tokens"] = min(1800, kwargs.get("max_tokens") or 1800)
        reserve = (
            len(json.dumps(kwargs["messages"]).encode()) + 256
        ) * 0.6 / 1e6 + 1800 * 2.4 / 1e6
        key = ledger.reserve(reserve, label=row["qid"])
        try:
            response = await create(
                **kwargs, extra_body={"thinking": {"type": "disabled"}}
            )
            usage = response.usage.model_dump()
            ledger.settle(
                key,
                usage,
                (usage["prompt_tokens"] * 0.6 + usage["completion_tokens"] * 2.4) / 1e6,
            )
            return response
        except BaseException:
            ledger.settle(key, {}, reserve, unknown_billing=True)
            raise

    sdk.chat.completions.create = bounded_create
    config = LLMConfig(model=MODEL, small_model=MODEL, temperature=0, max_tokens=1800)
    llm = OpenAIGenericClient(
        config=config, client=sdk, structured_output_mode="json_object", max_tokens=1800
    )
    bge = LocalBGE()
    db_class = kuzu.Database
    with patch.object(
        kuzu, "Database", lambda db: db_class(db, buffer_pool_size=96 * 1024**2)
    ):
        driver = KuzuDriver().with_database("person")
    graph = Graphiti(
        graph_driver=driver,
        llm_client=llm,
        embedder=bge,
        cross_encoder=NoCrossEncoder(),
        max_coroutines=2,
    )
    calls = Calls(out / "calls")
    start = time.monotonic()
    try:
        await graph.build_indices_and_constraints()
        # The Kuzu driver exposes schema DDL but its index setup is a no-op.
        for ddl in get_fulltext_indices(driver.provider):
            await driver.execute_query(ddl)
        for i, session in enumerate(row["sessions"]):
            before = len(events)
            await graph.add_episode(
                name=f"session {i}",
                episode_body=session,
                source=EpisodeType.message,
                source_description="Conversation between one user and assistant",
                reference_time=dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
                + dt.timedelta(days=i),
                group_id="person",
            )
            if len(events) - before > 32:
                raise ValueError("Graphiti episode call limit")
        edges = await graph.search(
            row["question"], group_ids=["person"], num_results=24
        )
        evidence = [
            e.fact for e in edges if e.invalid_at is None and e.expired_at is None
        ][:12]
        ans = calls.ask(
            READ, {"question": row["question"], "evidence": evidence}, "reader"
        )["answer"]
        result = {
            "qid": row["qid"],
            "arm": "graphiti",
            "answer": ans,
            "correct": bool(scorer.answer_matches(ans, row["answer"])),
            "stale": bool(scorer.stale_use_penalty(ans, row["stale_values"])),
            "n_sessions": len(row["sessions"]),
            "calls": events + calls.events,
            "embedding": bge.stats,
            "elapsed": time.monotonic() - start,
        }
        write_json(out / (row["qid"] + "__graphiti.json"), result)
    finally:
        await graph.close()
        await sdk.close()


def main():
    p = argparse.ArgumentParser()
    for k in ("data", "out", "reward"):
        p.add_argument(k, type=Path)
    p.add_argument("--limit", type=int)
    p.add_argument("--offset", type=int, default=0)
    a = p.parse_args()
    (a.out / "calls").mkdir(parents=True, exist_ok=True)
    s = load_reward(a.reward)
    rows = [json.loads(x) for x in a.data.open()][a.offset :][: a.limit]
    for row in rows:
        if not (a.out / (row["qid"] + "__graphiti.json")).exists():
            asyncio.run(run(row, a.out, s))


if __name__ == "__main__":
    main()
