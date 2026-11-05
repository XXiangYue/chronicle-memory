# Chronicle

Source-aware, time-aware long-term memory with compact evidence and retrieval fallback.

## Repeated fact changes

On 200 public synthetic Supersede conversations, the Graphiti reference system answered **159/200** current-value questions correctly, compared with **186/200** for Chronicle. Answers containing an obsolete value fell from **24 to 2**. Per 100 input sessions, logical write volume was **517,951 vs 17,852** model tokens. Both used deepseek-flash. Each conversation updated one of four personal attributes. The shared-extractor latest-mention baseline scored 183/200 with two stale answers and selected the same source quotations as Chronicle throughout.

The cross-dataset check exposed the scope of this result. On LongMemEval-S knowledge updates, the new ledger answered **12/72** answerable questions and abstained correctly on **6/6**. One failed extraction is included in the answerable denominator. [Experiment, raw results and reproduction](docs/FACT_UPDATES.md).

```bash
uv run python scripts/revision_report.py verify results/revisions_v2
```

## Earlier retrieval experiment

On 500 LongMemEval-S questions, ordinary retrieval scored 259/500 and memory with fallback scored 301/500 under the declared model judge. Reader input fell 20.7%.

**Scope and negative findings:** 282/500 extraction attempts fell back to retrieval. Primary ingestion cost is recorded separately; reader-token reduction is not total cost reduction. These are custom model-judged results, not official leaderboard or human-validated accuracy.

The 500-question retrieval measurements were made on **2026-11-01** in the original integrated workspace.
The standalone packaging was prepared on **2026-11-05**. Packaging checks are
reported separately in `VALIDATION.json`; they are not new model benchmark runs.

## Quick start

Use **Python 3.12**, `uv`, and macOS or Linux. Run commands from this checkout.


```bash
git clone https://github.com/XXiangYue/chronicle-memory.git
cd chronicle-memory
uv sync --locked
uv run pytest -q
uv run python scripts/verify_results.py
uv run python scripts/fetch_data.py
```


Inference requires `OUTCOMES_API_KEY` in the process environment. Supply it using
your normal secret manager; no key is required for tests or saved-result verification.
`OUTCOMES_API_BASE` and `OUTCOMES_MODEL` are optional. The evaluated model identifiers
are `deepseek-flash` and `deepseek-v4-pro`. Historical peak-equivalent prices in
`model.py` describe the original accounting policy, not a current price quote.
The per-repository ledger has the retained 75 USD peak-equivalent conservative ceiling; choose a
small run first. Separate repositories have separate ledgers, not a shared cap.


```bash
uv run chronicle ingest --db runtime/demo.sqlite --namespace demo --sources examples/sources.json
# API inference and first-use embedding download:
uv run chronicle query --db runtime/demo.sqlite --namespace demo --question "What is the budget?" --known-at 2026-10-31 --as-of 2026-10-31
```

See [running and reproduction](docs/RUNNING.md), [results and limits](docs/RESULTS.md),
[architecture](docs/ARCHITECTURE.md), and [source attribution](THIRD_PARTY.md).
For a Chinese overview, see [中文说明](README.zh-CN.md).

## What is in the repository

- `src/chronicle/`: independently installable project code and project-specific CLI.
- `tests/`: offline domain and retained regression checks.
- `results/`: measured per-trial exports, protocols, summaries and source hashes.
- `scripts/verify_results.py`: recomputes the primary published counts without inference.
- `protocols/P2.json`: original design protocol; original runs lock later amendments.
- `PROVENANCE.json`: source commit, original/published file hashes and packaging changes.

This is personal portfolio engineering. Historical employer results and private
workplace material are not included. Original code has no newly assigned blanket
license in this packaging operation; vendored components retain their licenses.

First-use tiktoken may fetch public tokenizer data once; contract tests do not call inference providers.
