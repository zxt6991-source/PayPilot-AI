# 支付诊断时间范围复测

2026-11-21，修正滚动时间表达后，用 8 道新编合成题评估规则与 DeepSeek。两个模式在 4 道明确窗口题上都选中了正确周期，报告分母均通过独立 SQL 复算。在 4 道需要澄清的题上，两个模式都保留已有条件、只询问周期，且查询工具调用数为零。

| 模式 | 时间范围处理 | 全项通过 | 未通过项 |
|---|---:|---:|---|
| demo-rules-v1 | 8/8 | 7/8 | h08 请求看两个时间口径，规则将“口径”判为知识问答，题目预期为诊断 |
| deepseek-flash，温度 0 | 8/8 | 8/8 | 全部通过，共记录 4,824 tokens |

例如，新加坡 Card 的 Web 支付按 thirty-day 查询，报告给出 1,078 次有效尝试。要求过去 48 小时的任务会暂停，界面提示选择最近 24 小时、7 天或 30 天；用户确认后沿用原任务继续。API 集成测试覆盖文字回复和结构化选择，检查实际取数窗口起止相差 7 天。

该专项集在运行前冻结，仅考察固定演示数据中的滚动周期、自然月和多窗口请求。历史 20 题首次对照仍按当时的实现解读。模型实际金额待账单核对。真实用户对澄清流程的体验仍待访谈。

按 README 配置独立评测库及服务端模型凭据后，可在仓库根目录复现。runner 会保存每道题的检查结果，存在未通过项时退出码为 1。

```sh
shasum -a 256 -c evaluation/datasets/period-holdout-v1.sha256
LLM_PROVIDER=rules .venv/bin/python evaluation/runner.py --dataset evaluation/datasets/period-holdout-v1.jsonl
LLM_PROVIDER=deepseek LLM_MODEL_ID=deepseek-flash .venv/bin/python evaluation/runner.py --dataset evaluation/datasets/period-holdout-v1.jsonl
```

[冻结题目](../datasets/period-holdout-v1.jsonl) · [规则逐题结果](../results/experiments/rules-custom-esif_8_c/custom.jsonl) · [模型逐题结果](../results/experiments/deepseek-custom-p79bnu1v/custom.jsonl) · [首次 20 题对照](real-model-v1.md)

## 11 月 22 日同题回归

针对 h08 的意图误判，规则现在能区分“两个口径分别统计”和“解释 PSR 分母的口径”。前者先询问周期，选定 7 天后在同一任务里查询支付数据；后者检索知识出处。新措辞的 API 集成测试核对了最终报告的周期和分母，也检查了知识问答的来源引用。

修复后，同一组 8 题的规则回归通过 8/8。该结果用于确认已知问题的修复，首次冻结评测仍为规则 7/8、DeepSeek 8/8。上方 SHA-256 清单标识首次运行时的源码版本。[修复后逐题记录](../results/experiments/rules-custom-1zhq4k9m/custom.jsonl)
