# 固定留出集验收

分层留出 20 条，v0.4 在完成单测修复并固定评分器后运行。指标查询 4/4，异常诊断 5/5，多维比较 4/4，知识问答 3/3，数据缺失与歧义 2/2，安全边界 2/2。每个用例均计入分母。

逐例可按 case_id 对应 evaluation/datasets/cases_v1.jsonl、results/holdout.jsonl 中的期望、检查项和 Trace。评测机本地 paypilot_eval 留存任务、证据与报告。独立机器重新执行会产生新的 run_id。数据和切分哈希见 results/holdout-summary.json。
