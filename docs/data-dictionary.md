# DEMO 数据字典

| 表 | 主键或业务唯一键 | 字段语义 |
|---|---|---|
| payment_attempts | payment_attempt_id | 一次尝试、一条规范化最终记录。order_id_hash 可重复。created_at 用于队列统计，finalized_at 用于成熟终态窗口。channel、app_version、error_code 支持下钻。dataset_version、seed_batch_id、environment 标识模拟批次。 |
| release_events | release_id | 终端、版本、发布时间及自编变更说明，供相关性核查。 |
| diagnosis_tasks | task_id；owner + idempotency_key | 初始问题、初始筛选、数据版本、请求摘要及 current_run。 |
| agent_runs | run_id | 当前状态、运行问题与实际筛选、parent_run、模型/提示/流程版本、步数、起止时间与终止原因。 |
| agent_steps | run_id + sequence | 节点、开始与结束时刻。 |
| agent_events | run_id + sequence | SSE 事件名、友好载荷及提交时间。 |
| tool_invocations | invocation_id；run + tool + 参数摘要 | 工具调用生命周期、耗时、关联证据。 |
| diagnosis_evidence | evidence_id | 运行归属、工具来源、查询参数、结果快照与数据版本。 |
| diagnosis_reports | report_id；run_id | 结构化 JSON、schema 版本与创建时间，每个完成 run 一份报告。 |
| diagnosis_feedback | feedback_id | run 与 report 的关联、是否有帮助、标签及备注。 |
| knowledge_documents | document_id | 自编 DEMO 标题、来源、版本、适用条件、更新时间与激活标志。 |
| knowledge_chunks | chunk_id | 文档键、段落顺序、标题位置与正文。chunk_id 含内容摘要。 |

支付事实与知识由初始化角色维护。metric_reader 只读事实和知识，app_user 持久化运行信息。SQLAlchemy 表定义见 backend/app/db.py，Alembic 迁移见 backend/migrations。
