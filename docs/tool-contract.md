# 只读工具协议

Registry 持有六项固定能力。调用者指定 run、预期运行状态、已注册名称与严格参数。额外字段、非法枚举、未经授权的角色会被拒绝。每次调用使用独立的只读连接。默认每项工具超时 10 秒。

| 工具 | 输入 | 保存的事实 |
|---|---|---|
| get_payment_metrics | Scope | 成功、失败、待决、取消、分母、窗口与质量标记 |
| compare_payment_periods | Scope | 当前与两段合并基准及 pp 差异 |
| get_failure_breakdown | Scope、白名单 dimension | 各组样本、PSR、基准与差异 |
| get_error_distribution | Scope，可指定终端 | 每个演示码数量、失败分母、占比 |
| get_release_changes | Scope | 窗口内的模拟发布事件 |
| search_payment_kb | 筛选与 query | 至多三个带位置、版本、来源的 chunk，或空召回/冲突 |

Scope 包含地区、支付方式、终端、周期、版本与回放时间。任务 ID、运行 ID、证据 ID 分别以 task_、run_、ev_ 开头。成功时在同一事务写入证据与 tool.completed 事件。工具返回 payload 给工作流，完整 ToolResult 从审计行及其 evidence_id 读取。幂等键由 run、工具名和规范化 JSON 参数的 SHA-256 构成。

取消与超时后不会采纳迟到结果。已经发出的只读查询可以自然结束。工具没有支付写入、任意 SQL、Shell 或动态网络目的地的入口。
