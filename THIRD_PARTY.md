# Source and attribution

The project was separated from the author's integrated implementation commit
`f6818662fdf4d845732545c34b63776a3960b694`. `PROVENANCE.json` binds copied files to original hashes. Python package
names and the CLI were adapted for standalone use; historical measurements stay
bound to their original commit and protocols.

Chronicle is informed by the eligibility-before-ranking design in [XXiangYue/changjuan](https://github.com/XXiangYue/changjuan), commit 40ee68143c1e45fe5e6093598a677c88d3eb2750. The new memory module is implemented here. The official LongMemEval evaluation prompt source is vendored under its retained MIT license in upstream/LICENSE.longmemeval; dataset URLs and hashes are in data/download_manifest.json.




Third-party files retain their original license notices. This packaging operation
does not assign a new blanket license to the author's original portfolio code.

The 2026-11-05 revision benchmark downloads the [Supersede episodes](https://huggingface.co/datasets/vedant33/supersede-rl-episodes), the upstream [Supersede scorer](https://github.com/Vrin-cloud/supersede) and the [Graphiti](https://github.com/getzep/graphiti) package under their respective terms. BGE-M3 was served through Ollama for the graph arm. Input data and upstream scorer hashes are pinned in `scripts/fetch_revision_data.py`. The public result rows contain IDs, generated short Supersede answers, scores and numeric usage.
