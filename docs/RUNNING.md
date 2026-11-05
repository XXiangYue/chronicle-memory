# Running Chronicle

The later paired comparison of Graphiti, latest mention and Chronicle, with LongMemEval transfer and exact reproduction commands, is documented in [FACT_UPDATES.md](FACT_UPDATES.md).

## Environment

Use Python 3.12 and the checked-in `uv.lock`. `uv sync --locked` installs an
editable checkout in its own virtual environment. Run from the repository root;
the source intentionally locates project assets relative to that checkout.
Linux/macOS are supported; Windows users can use WSL2. CPU runs do not require CUDA.

## Three different verification levels

1. `uv run pytest -q`: offline contracts and regression witnesses; provider fixtures
   are explicitly simulated and are not model-effectiveness evidence.
2. `uv run python scripts/verify_results.py`: recomputation from published rows
   of historical measurements; no inference or new performance claim.
3. The project commands below: fresh execution under your own environment. Use
   a new output directory. Changed models, prompts, dependencies or assets define
   a new run and need their own result label.

```bash
uv run chronicle ingest --db runtime/demo.sqlite --namespace demo --sources examples/sources.json
# API inference and first-use embedding download:
uv run chronicle query --db runtime/demo.sqlite --namespace demo --question "What is the budget?" --known-at 2026-10-31 --as-of 2026-10-31
```


Inference requires `OUTCOMES_API_KEY` in the process environment. Supply it using
your normal secret manager; no key is required for tests or saved-result verification.
`OUTCOMES_API_BASE` and `OUTCOMES_MODEL` are optional. The evaluated model identifiers
are `deepseek-flash` and `deepseek-v4-pro`. Historical peak-equivalent prices in
`model.py` describe the original accounting policy, not a current price quote.
The per-repository ledger has the retained 75 USD peak-equivalent conservative ceiling; choose a
small run first. Separate repositories have separate ledgers, not a shared cap.


## Results and troubleshooting

`results/` is a read-only historical export. New runs go under `runtime/` or a new
chosen directory. The code refuses a conflicting frozen protocol. Do not reuse
an old terminal output directory for a changed configuration.

Download the required public data with `uv run python scripts/fetch_data.py`. It verifies the recorded size and SHA-256 and fails on a changed download. Datasets, downloaded models and caches are excluded from Git. A network timeout or hash mismatch is a preparation failure, not a successful evaluation.


First-use FastEmbed may download the declared BGE model. Extracted notes and deletion are source-dependent. Logical deletion excludes data from retrieval; it does not physically erase old databases or logs. `evaluate-public --out runtime/public-1 --limit 3` is a small paid probe; omit `--limit` for the full 500-question, three-arm evaluation. `evaluate-custom --out runtime/custom-1 --split test` runs the custom corpus. These two corpora must be reported separately.



If inference credentials are absent, an explicit configuration error is expected.
No embedded fallback response is substituted for real inference.

First-use tiktoken may fetch public tokenizer data once; contract tests do not call inference providers.
