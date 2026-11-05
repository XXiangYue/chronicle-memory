# Measured results and interpretation

The later paired comparison of Graphiti, latest mention and Chronicle, with LongMemEval transfer and exact reproduction commands, is documented in [FACT_UPDATES.md](FACT_UPDATES.md).

On 500 LongMemEval-S questions, ordinary retrieval scored 259/500 and memory with fallback scored 301/500 under the declared model judge. Reader input fell 20.7%.

282/500 extraction attempts fell back to retrieval. Primary ingestion cost is recorded separately; reader-token reduction is not total cost reduction. These are custom model-judged results, not official leaderboard or human-validated accuracy.

## Evidence and reproduction

The original commit is `f6818662fdf4d845732545c34b63776a3960b694`. The measurement date is 2026-11-01.
`results/SOURCE_MANIFEST.json` lists original file hashes. `results/` contains
per-trial numeric/state exports, not all original databases or model transcripts.
Private workstation paths were normalized. Benchmark source text, downloaded
models, credentials and API request identifiers are excluded. Constructed Quality
Gate corpus data is published because it was authored for this experiment.

Run `uv run python scripts/verify_results.py` to recompute primary numbers.
The script verifies observed numerators, denominators and token totals against
the published summaries. It does not independently validate model judgments.
Fresh-run instructions are in [RUNNING.md](RUNNING.md).

## Additional findings to preserve


M0 recent context scored 59/500; M1 retrieval 259/500; M2 memory with fallback 301/500. Reader input totals were 4,025,395 tokens for M1 and 3,194,028 for M2. The public run had 1,500 requested records; one M0 attempt lacked a judge result. Public ingestion was 18.12143 USD peak-equivalent upper bound, not a full invoice or total saving. The separate temporal/deletion/scope witness had correct eligibility 18/18 but correct answers only 11/18, which prevents equating eligible retrieval with correct reasoning.


