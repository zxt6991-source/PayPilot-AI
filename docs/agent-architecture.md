# 自研 Agent 的运行与恢复

FastAPI 将任务与 run 在同一事务创建后返回 HTTP 202。单进程后台执行器驱动数据库状态机。React 使用状态快照及 SSE 监听，一次订阅不触发执行。已登录演示身份只可访问所属任务及历史报告。

```text
创建 → 解析 → 读取指标 → 终端与错误码下钻 → 检索 → 校验 → 保存报告
        ↓ ↑          ↓
       等待澄清      样本不足
```

知识问答从解析直接进入检索。工具拒绝、证据不足、执行失败与用户取消都有可查看的原因。单次连续执行默认限时 30 秒，最大配置步数为 8；等待澄清时没有运行中的模型调用。进程启动扫描未完成工作，重新进入当前节点，复用已成功且参数相同的工具证据。模型请求若在响应持久化前中断，重启后可能重发。在这个本地版本中，API 必须使用单 worker。

| 操作 | HTTP 接口 |
|---|---|
| 健康、快照 | GET /api/health |
| 确定性统计 | GET /api/metrics 及 /compare、/breakdown、/errors、/trend |
| 创建 | POST /api/diagnoses，可传 Idempotency-Key |
| 任务及历史 run | GET /api/diagnoses/{task_id}，可选 run_id |
| 订阅增量 | GET /api/diagnoses/{task_id}/events，支持 run_id、after 或 Last-Event-ID |
| 澄清、追问、重试 | POST /api/diagnoses/{task_id}/messages，携带已知 run_id、question 与可选 filters |
| 停止 | POST /api/diagnoses/{task_id}/cancel，携带当前 run_id |
| 反馈 | POST /api/diagnoses/{task_id}/feedback，携带 run_id、report_id、rating、note |
| 报告、知识、评测 | GET /api/reports/{report_id}、/api/knowledge、/api/evaluation |

SSE ID 为 run_id:sequence。事件先落库，同一事务还会提交对应状态更新。浏览器消费事件后读取权威快照，根据事件序号渲染轨迹。断线重放指定游标之后的事件；报告通过独立 URL 打开。终态追问创建新 run 并记录 parent_run，原报告可继续审核。
