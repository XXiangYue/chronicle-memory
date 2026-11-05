# Chronicle 中文导读

新版本聚焦用户更正个人信息后，助手能否答出当前值。Supersede 的 200 条公开合成对话涵盖城市、雇主、汽车和宠物。相同回答模型下，Graphiti 答对 159 条，Chronicle 答对 186 条。答案含旧值 24→2 次，每百段会话写入消耗从约 51.8 万降至 1.79 万模型 tokens。简单的“取最新相关提及”也答对了 183 条，三组全部完成。两种轻量方法在 200 条中取到的原文相同，三题差别只出现在带会话编号的回答环节。

在更复杂的 LongMemEval-S 更新题中，Chronicle 在 72 道可答题中答对 12 道，另 6 道不可答题全部正确拒答。完整逐题数据、成本口径与复现命令见[事实更新实验](docs/FACT_UPDATES.md)。

旧版处理跨会话信息、时点、更正和删除。公开500题中，普通检索259题、记忆与降级链路301题被模型裁判判定答对，Reader输入减少20.7%；保留282次抽取回退与构建成本。

这是独立可安装的个人工程项目。历史测量在2026年11月1日完成，拆仓和事实更新对照实验分别留档。

先按英文 [README](README.md) 安装，再运行：

```bash
uv sync --locked
uv run pytest -q
uv run python scripts/verify_results.py
uv run python scripts/revision_report.py verify results/revisions_v2
```

以上命令覆盖依赖安装、离线回归和历史结果复算。需要真实模型调用的命令另见 [运行说明](docs/RUNNING.md)，需自行通过环境变量提供凭据。评测结果及适用范围见 [结果说明](docs/RESULTS.md)，逐条结果在 `results/`。本仓库不包含企业内部材料、访问密钥、大型模型缓存或原始数据库。
