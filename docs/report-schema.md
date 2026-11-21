# 报告与证据校验

Pydantic DiagnosisReport 定义在 backend/app/schemas.py。顶层包含 schema_version、run_id、report_id、dataset_version、environment、status、scope、metrics、findings、hypotheses、citations、actions、uncertainties。知识问答的 metrics 为 null。统计报告用原始比例，前端负责格式化。

生成报告前按 run 读取持久化证据。PSR 与分母来自 get_payment_metrics 和 compare_payment_periods 的一致投影。每项事实都带 evidence_ids，回跳假设同时引用错误分布与检索快照。校验器核对范围、版本、报告声明与证据投影，并确认每条引用既属于本次召回又能在 PostgreSQL 定位。

模型仅可提交约束内的意图及建议选项。草稿建议生成失败会降级，报告载明原因。知识无命中、版本冲突、样本不足或基准缺失分别保留提示。所有诊断结论保持待验证状态。归一化错误码的定义和演示发布记录均使用项目自编来源。
