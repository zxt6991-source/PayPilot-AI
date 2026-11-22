# 首次冻结挑战集上的支付诊断对照

2026-11-21，在同一批 30,000 笔合成支付尝试上，规则模式通过 13/20，DeepSeek 模式通过 19/20。两种模式共用支付查询、证据装配和终端范围校验。规则通过的 13 题，模型模式均通过。

| 任务 | 规则 | DeepSeek |
|---|---:|---:|
| 自然表达 | 1/4 | 4/4 |
| 中英混合 | 1/3 | 3/3 |
| 条件修正 | 3/4 | 3/4 |
| 缺失条件 | 3/3 | 3/3 |
| 只读边界 | 2/3 | 3/3 |
| 知识证据与空数据 | 3/3 | 3/3 |

**哪些问题影响决策。** 规则在 01、05、06 题识别出地区和支付方式，却把“过去一周”“30-day”“last seven days”按默认 24 小时查询，生成了范围错误的报告。02、03 题对地区别称等表达发起了多余澄清。17 题要求修改支付状态，规则询问了筛选条件，未执行工具；模型模式正确拒绝。两种模式在其余 17 个合法任务上的误拒绝均为 0/17。

两种模式共同失败的是第 09 题。“我是说 iOS，不是 Web”已经指定 iOS，共用的终端校验仍要求确认。该题在查询前暂停。它和静默查错时间窗的处理优先级不同。下一轮应先让系统在无法解释明确时间表达时询问用户，再减少明确改口导致的额外追问。此轮保留冻结结果，任何针对这 20 题的修复另用新题验证。

**耗时与用量。** 全部 20 题串行，规则 P50 / P95 为 0.006 / 0.032 秒，DeepSeek 为 1.347 / 2.690 秒。计时从本地 ASGI 提交到可用状态，包含数据库和实际模型网络请求。模型 deepseek-flash，温度 0，18 题有用量事件，共 10,156 输入、780 输出，合计 10,936 tokens。两题在调用模型前拒绝。实际金额待对账。此次测量覆盖系统响应，用户阅读和升级排查工时待首访及任务研究。

**评测边界。** 20 道题由本项目编写，来自合成场景，题面与现有数据文件去重。题库和候选实现于运行前记录 SHA-256，两个模式各运行一次。所有题均进入分母。每题检查其预设金标；查询题要求报告范围和可复算数值正确，澄清题核对所问字段、已知条件和暂停时工具调用数。冻结集是首次使用的项目内挑战集，真实用户措辞和人工证据支持率仍需单独核实。

在已有固定种子数据的独立评测库中运行下列命令。先配置三个数据库连接和服务端模型凭据。某些题未通过时，runner 会保存原始记录并返回退出码 1。

```sh
shasum -a 256 -c evaluation/datasets/challenge-holdout-v1.sha256
LLM_PROVIDER=rules .venv/bin/python evaluation/runner.py --dataset evaluation/datasets/challenge-holdout-v1.jsonl
LLM_PROVIDER=deepseek LLM_MODEL_ID=deepseek-flash .venv/bin/python evaluation/runner.py --dataset evaluation/datasets/challenge-holdout-v1.jsonl
```

[冻结清单](../datasets/challenge-holdout-v1.sha256) · [题目和预期](../datasets/challenge-holdout-v1.jsonl) · [逐题规则结果](../results/experiments/rules-custom-9om6f40z/custom.jsonl) · [逐题模型结果](../results/experiments/deepseek-custom-q2t4enis/custom.jsonl) · [六道终端开发题复测](../results/experiments/rules-custom-jbp3vu_w/custom-summary.json)
