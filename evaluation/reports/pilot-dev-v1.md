# 四道支付诊断开发题的首次对照

2026-11-21，固定 30,000 条 demo-v1 合成支付尝试，workflow-v0.4 / kb-v1。四题由项目开发阶段编写，按外部预期状态、意图、查询范围等逐题判分。有范围金标的报告再用 SQL 复算支付指标。全部发起题目均计入分母。这组题已用于规则调整，独立盲测另行开展。

| 开发题 | 初始规则 | DeepSeek | 修正规则后 |
|---|---|---|---|
| 德区、过去一天、安卓端 | 请求补充地区 | 正确完成 | 正确完成 |
| 先别看 Android，只要 Web | 正确完成 | 正确完成 | 正确完成 |
| 英国，尚未选支付方式 | 询问支付方式 | 询问支付方式 | 询问支付方式 |
| 发起演示退款 | 本地拒绝 | 本地拒绝 | 本地拒绝 |
| 全项通过 | 3/4 | 4/4 | 4/4 |
| 提交至获得状态的中位耗时 | 0.011 秒 | 1.762 秒 | 0.021 秒 |

**产品决定。** 第一题在初始规则下丢失地区，报告没有生成。模型识别了明确的地区和终端。为规则加入“德区”“安卓”“过去一天”，复测能得到正确范围和分母。当前为这些明确说法保留规则路径。第二题的单个语序不足以支持对任意否定表达的判断，后续未见集应覆盖改口、条件顺序互换和确实需要澄清的表达。

**用量和计时。** 模型为 deepseek-flash，温度 0，三道调用模型的题分别记录 715、689、524 tokens，合计 1,793 输入、135 输出。退款请求在模型调用前被拦截。金额待供应商账单核对。耗时包含本地 ASGI 请求、PostgreSQL 工具和实际模型往返，未计浏览器渲染及人工阅读。四题任务混合，最慢的模型任务为 3.675 秒。用户任务耗时与人工引用支持率仍待测量。

**复现。** 在独立评测库完成迁移与固定种子导入，并为当前 shell 设置 README 所列三个数据库 URL。从仓库根目录运行：

```sh
LLM_PROVIDER=rules .venv/bin/python evaluation/runner.py --dataset evaluation/datasets/pilot-dev-v1.jsonl
# DeepSeek 需已在当前 shell 配置服务端凭据
LLM_PROVIDER=deepseek LLM_MODEL_ID=deepseek-flash .venv/bin/python evaluation/runner.py --dataset evaluation/datasets/pilot-dev-v1.jsonl
```

当前规则命令复现修正后的行为。三个汇总的题库 SHA-256 一致，逐题 JSONL 位于各汇总旁；其中包含范围、终态、检查项、用量事件和耗时。[题目与预期](../datasets/pilot-dev-v1.jsonl) · [初始规则](../results/experiments/pilot-v1-rules/custom-summary.json) · [DeepSeek](../results/experiments/deepseek-custom-k30y3avd/custom-summary.json) · [修正规则](../results/experiments/rules-custom-53eizs9o/custom-summary.json)
