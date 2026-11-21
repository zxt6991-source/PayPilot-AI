import { useEffect, useState } from "react";

export async function api<T>(
  path: string,
  body?: unknown,
  key?: string,
): Promise<T> {
  const res = await fetch(
    "/api/" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(key ? { "Idempotency-Key": key } : {}),
          },
          body: JSON.stringify(body),
        },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `请求失败（${res.status}）`,
    );
  }
  return res.json();
}

export function useResource<T>(key: string, load: () => Promise<T>) {
  const [result, set] = useState<{ key: string; data?: T; error?: string }>({
    key: "",
  });
  useEffect(() => {
    let active = true;
    load()
      .then((data) => {
        if (active) set({ key, data });
      })
      .catch((e) => {
        if (active) set({ key, error: String(e.message) });
      });
    return () => {
      active = false;
    };
  }, [key]);
  return result.key === key ? result : { key };
}
export const pct = (v: number | null) =>
  v === null ? "—" : (v * 100).toFixed(1) + "%";
export const pp = (v: number | null) =>
  v === null ? "—" : (v > 0 ? "+" : "") + Number(v.toFixed(2)) + " pp";
export const time = (v: string) =>
  new Date(v).toLocaleString("zh-CN", { timeZone: "UTC", hour12: false });
export type Scope = {
  country_code: string;
  payment_method: string;
  period: string;
  channel?: string;
  as_of?: string;
};
export type Sample = {
  valid_attempts: number;
  successful_attempts: number;
  failed_attempts: number;
  psr: number | null;
  quality_flags: string[];
};
export type Metrics = Sample & {
  pending: number;
  cancelled: number;
  as_of_utc: string;
  query_window: { start_at: string; end_at: string };
};
export type Compare = {
  current: Sample;
  baseline: Metrics;
  delta_pp: number | null;
};
export type Split = { value: string; delta_pp: number | null } & Sample;
export type ErrorRow = {
  error_code: string;
  count: number;
  share_of_failures: number;
};
export type Chunk = {
  chunk_id: string;
  document_id: string;
  title: string;
  content: string;
  location: string;
  version: string;
  source: string;
};
export type Claim = { text: string; evidence_ids: string[] };
export type Report = {
  report_id: string;
  run_id: string;
  scope: Scope;
  metrics: null | {
    valid_attempts: number;
    current_psr: number | null;
    baseline_psr: number | null;
    delta_pp: number | null;
    evidence_ids: string[];
  };
  findings: Claim[];
  hypotheses: Claim[];
  citations: string[];
  actions: string[];
  uncertainties: string[];
};
export type Run = {
  task_id: string;
  run_id: string;
  state: string;
  question: string;
  filters: Scope;
  reason: string | null;
  model_id: string;
  workflow_version: string;
  report: Report | null;
  events: {
    sequence: number;
    event_type: string;
    payload: { state?: string; tool?: string };
  }[];
  evidence: {
    evidence_id: string;
    source_key: string;
    payload: { hits?: Chunk[] } & Record<string, unknown>;
  }[];
};
export type Accepted = Pick<Run, "task_id" | "run_id" | "state">;
export const paused = (state: string) =>
  [
    "FAILED",
    "COMPLETED",
    "CANCELLED",
    "INSUFFICIENT_DATA",
    "CLARIFYING",
  ].includes(state);
export const states: Record<string, string> = {
  CREATED: "已创建",
  PARSING: "解析问题",
  CLARIFYING: "等待补充条件",
  QUERYING: "读取支付指标",
  ANALYZING: "下钻异常",
  RETRIEVING: "检索知识库",
  VALIDATING: "校验证据",
  COMPLETED: "诊断完成",
  CANCELLED: "已取消",
  INSUFFICIENT_DATA: "无法判定",
  FAILED: "执行失败",
};
