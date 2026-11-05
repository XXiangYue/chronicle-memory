# Current personal facts after repeated updates

A conversation assistant that hears a correction has to decide which statement still applies. This evaluation compares the cost and answer quality of maintaining one person's standing facts in a small revision ledger with maintaining a general temporal knowledge graph. The unit of evaluation is one independent conversation ending in one query.

## Supersede test results

All three systems answered all 200 conversations. These public synthetic conversations contain 1,418 sessions covering four questions about the speaker's current city, employer, car or pet. The frozen protocol is in [value-v2.json](../protocols/value-v2.json). The first 20 training episodes were used for development of the lightweight arms (both 17/20). The final Graphiti adapter was smoke-tested on one training conversation. Gold facts and stale values enter scoring only.

| System under the same answer model | Current value correct | Answers containing an obsolete value | Write LM tokens per 100 sessions | All cold logical LM tokens |
|---|---:|---:|---:|---:|
| Graphiti 0.31.2, Kuzu and local BGE-M3 | 159/200 | 24/200 | 517,951 | 7,362,792 |
| Latest relevant mention after shared extraction | 183/200 | 2/200 | 17,852 | 290,812 |
| Chronicle revision ledger | 186/200 | 2/200 | 17,852 | 291,615 |

Compared with this Graphiti configuration, Chronicle answered 35 questions only it got right and missed 8 only Graphiti got right. The paired difference was +13.5 percentage points (episode bootstrap 95% interval +7.5 to +19.5). The stale-answer difference was −11.0 points (−16.0 to −6.5). All episodes count, including unknown answers. Deterministic official matching checks surface variants or token overlap for current answers and obsolete-value matches separately. In this run these outcomes did not overlap. The uncertainty calculation resamples the paired episodes with a fixed seed, 10,000 resamples. The four question templates limit generalization beyond these episodes. The graph builds entities and relationships for broader uses than the four tested questions.

The latest-mention baseline gave the clearest constraint on the interpretation. In all 200 episodes the two lightweight readers received the **same source quotes**. Chronicle prefixed its quotes with their session numbers. The three differences in judged correctness all involved a Toyota trade-in. Equalizing this reader formatting yields the same reader request wherever the evidence is the same. These results support using a cheaper specialized store on this workload. They provide no demonstrated additional benefit from temporary-fact handling on the held-out generator. The [offline evidence replay](../results/revisions_v2/light_evidence_audit.json) exposes the distinction per episode.

One failure can be inspected at `train_900134`. The final employer change to Vehement was extracted under “location.” The two lightweight systems both returned the previous employer, Initech. Graphiti returned Vehement. This illustrates the cost of committing to a small field schema.

## LongMemEval-S transfer

All 78 knowledge-update questions were attempted using the same Chronicle extraction, routing and reading prompts on chronological user turns. The official rubric text was evaluated by `deepseek-flash` via JSON. On the 72 answerable questions, **12/72** were judged correct, including one failed extraction as an unsuccessful attempt. On the six abstention questions, **6/6** were judged correct. Of the 77 episodes reaching the reader, 63 used the fallback of the last three sessions. A narrow set of canonical attributes transfers poorly to these longer multi-topic histories. Per-question outcomes and stage costs are in [longmemeval.jsonl](../results/revisions_v2/longmemeval.jsonl).

The transfer extraction output cap was relaxed on malformed JSON only (400, 1,200, 3,600, then 7,200 tokens). The scopes, prompts and scoring rule stayed fixed. The same ordered recovery policy was available for every item and was introduced after the first run encountered failures. One question still failed. The original transfer run had 23 parsing failures whose first malformed responses lacked saved usage. The initial unknown tokens and billing remain unknown. The transfer judge uses one model run without human regrading. The previous 500-question retrieval experiment used a different system, task mix and comparison and has its own [results](RESULTS.md).

## What was implemented

[Timeline](../src/chronicle/revisions.py) stores the attributed quote, owner, attribute, session and revision type. Duplicate sessions are idempotent, conflicting sessions are rejected, and every inserted quote must occur in the original session. By default, a query reads the latest standing revision for the requested participant and attribute alongside relevant uncertain evidence. The experiment uses the last three sessions only if this selection is empty. Both lightweight policies share a structured extractor and router. Their reader, model alias and temperature match the graph arm. A fresh in-memory ledger is opened per episode.

The [Graphiti adapter](../scripts/graphiti_arm.py) passes each raw session to the upstream incremental `add_episode` API with ordered reference dates. Each independent conversation gets an isolated in-memory Kuzu graph with a 96 MiB buffer, one group and populated full-text indices. Retrieval uses the default hybrid reciprocal-rank fusion, up to 24 candidate edges and at most 12 current edge facts after checking expiration and invalidation. Both the main and small graph LMs were configured as `deepseek-flash` with thinking disabled and a cap of 1,800 output tokens, compared with 400 for the dedicated extractor. Thus “compared with Graphiti” refers to this complete implementation and specific configuration. It does not estimate the effect of changing one Graphiti component. The deepseek-flash service alias and temperature 0 do not guarantee identical reruns.

## Token and retry accounting

The main table counts every observed prompt and output each time a completed episode logically uses it, including shared/cache-hit writes, question routing, reading, and fallback where applicable. Writes are normalized by 1,418 sessions, including sessions with no relevant facts. The cold logical token reduction was **96.0%** including answers and **96.6%** for writes. No fallback was used on Supersede. The specialized methods performed no embedding. Graphiti's successful executions additionally made 4,699 local BGE requests for 6,855 vectors (38,334 reported embedding tokens). Summed request duration was 669.8 seconds on the shared host. This is neither wall-clock speedup nor a model bill.

For visibility into failure costs, the [write ledger](../results/revisions_v2/graphiti_write_attempts.jsonl) also includes resumed graph attempts. It records 3,657 acknowledged writes consuming 7,326,034 input and 156,062 output tokens in total, compared with 3,589 acknowledged writes in the final successful episodes alone. There were 44 write requests with uncertain billing and two outstanding reservations after interruption. At the fixed conservative accounting rates of $0.60 and $2.40 per million input/output tokens, acknowledged graph-write usage is $4.7702, with up to another $0.4626 reserved or unknown. The resulting accounting upper bound applies to graph-write requests. Local embedding work from interrupted attempts was not metered.

The two light systems and all three final readers shared a hash-keyed model response cache. The Supersede test cache contains 808 distinct saved responses, 100,435 input and 15,276 output tokens in total across these shared calls. The [cache counters](../results/revisions_v2/usage.json) are shown separately from cold logical consumption. Invoice amounts for the individual systems cannot be recovered from a shared cache. The [summary](../results/revisions_v2/summary.json) breaks routing, reading, fallback and judging out from writing.

## Reproduce the comparison

From the repository root, check the saved runs without inference. The verifier rebuilds counts, costs and paired intervals from the published rows.

```bash
uv sync --locked
uv run python scripts/revision_report.py verify results/revisions_v2
uv run pytest -q
```

For fresh inference, supply `OUTCOMES_API_BASE` and `OUTCOMES_API_KEY` in your process environment. Use a new directory for each model or prompt configuration. Session data, model caches and service credentials are excluded from the public repository. The pinned Supersede files and official scorer are downloaded with SHA-256 verification.

```bash
uv run python scripts/fetch_revision_data.py runtime/updates-data
uv run python scripts/fetch_data.py
uv run python scripts/revision_report.py rescore results/revisions_v2 runtime/updates-data/test.jsonl runtime/updates-data/reward.py
uv run python scripts/supersede_eval.py runtime/updates-data/train.jsonl runtime/dev runtime/updates-data/reward.py --limit 20
uv run python scripts/supersede_eval.py runtime/updates-data/test.jsonl runtime/test runtime/updates-data/reward.py
```

Graphiti runs through its official Kuzu driver with local Ollama BGE-M3 listening on port 11434. The recorded embedding artifact had digest `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab` (F16). Verify the artifact after pulling. Run the same graph environment, including Python 3.12, for the isolated per-episode workers. These requests use a persistent $30 normalized graph-write ceiling. Smoke-test using `--limit 1` before running all episodes.

```bash
ollama pull bge-m3
uv venv --python 3.12 runtime/graph-env
uv pip install --python runtime/graph-env/bin/python 'graphiti-core[kuzu]==0.31.2' 'kuzu==0.11.3' 'openai==2.54.0' 'httpx==0.28.1' 'pydantic==2.14.2'
PYTHONPATH=src runtime/graph-env/bin/python scripts/graphiti_batch.py runtime/updates-data/test.jsonl runtime/test runtime/updates-data/reward.py --workers 4
uv run python scripts/longmem_transfer.py data/cache/longmemeval_s_cleaned.json runtime/transfer upstream/longmemeval_evaluate_qa.py
uv run python scripts/revision_report.py export runtime/updates-data/test.jsonl runtime/test runtime/transfer runtime/updates-report
uv run python scripts/audit_revision_evidence.py runtime/updates-data/test.jsonl runtime/test/calls runtime/updates-report/light_evidence_audit.json
```

Graphiti errors are recorded under the run's logs. Relaunching the same command preserves completed episodes, and each missing episode starts from a clean graph. Transfer extraction errors appear in the errors directory, with unsuccessful attempts counted in the transfer denominator. For reproducibility, the [official Supersede data](https://huggingface.co/datasets/vedant33/supersede-rl-episodes/tree/e44c0852a727d17a9c3f38022691fd7fa285ff8c), [official scorer](https://github.com/Vrin-cloud/supersede/blob/677993d3713c265329ac935262d3c08cbfa4cd63/src/supersede/reward.py), [Graphiti](https://github.com/getzep/graphiti) and [LongMemEval](https://github.com/xiaowu0162/LongMemEval) provide the upstream material.
