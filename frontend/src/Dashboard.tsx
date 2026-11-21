import { useState } from "react";
import {
  api,
  useResource,
  pct,
  pp,
  time,
  Scope,
  Metrics,
  Compare,
  Split,
  ErrorRow,
  Sample,
  Accepted,
} from "./api";

export const countries: Record<string, string> = {
  DE: "德国",
  GB: "英国",
  SG: "新加坡",
};
export function Icon({ name }: { name: string }) {
  return (
    <svg className="icon" aria-hidden="true">
      <use href={"/icons.svg#i-" + name} />
    </svg>
  );
}
export function Filter({
  label,
  value,
  options,
  change,
}: {
  label: string;
  value: string;
  options: Record<string, string>;
  change: (v: string) => void;
}) {
  return (
    <label>
      {label}
      <select
        aria-label={label}
        value={value}
        onChange={(e) => change(e.target.value)}
      >
        {Object.entries(options).map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
    </label>
  );
}
export function Dashboard() {
  const initial = new URLSearchParams(location.search);
  const [scope, set] = useState<Scope>({
    country_code: initial.get("country") || "DE",
    payment_method: initial.get("method") || "Klarna",
    period: initial.get("period") || "24h",
    channel: initial.get("channel") || "",
  });
  const [busy, loading] = useState(false),
    [err, error] = useState("");
  function change(k: keyof Scope, v: string) {
    const s = { ...scope, [k]: v };
    set(s);
    history.replaceState(
      {},
      "",
      "/dashboard?" +
        new URLSearchParams({
          country: s.country_code,
          method: s.payment_method,
          period: s.period,
          ...(s.channel ? { channel: s.channel } : {}),
        }),
    );
  }
  const query =
    "?" + new URLSearchParams(Object.entries(scope).filter(([, v]) => v));
  const { data, error: failed } = useResource(query, () =>
    Promise.all([
      api<Metrics>("metrics" + query),
      api<Compare>("metrics/compare" + query),
      api<{ rows: Split[] }>("metrics/breakdown" + query),
      api<{ rows: ErrorRow[] }>("metrics/errors" + query),
      api<{ rows: (Sample & { start_at: string })[] }>("metrics/trend" + query),
    ]),
  );
  async function start() {
    loading(true);
    error("");
    try {
      const t = await api<Accepted>(
        "diagnoses",
        {
          question: "分析所选范围的支付成功率变化和失败原因",
          filters: { ...scope, channel: scope.channel || null },
        },
        crypto.randomUUID(),
      );
      location.assign("/diagnoses/" + t.task_id);
    } catch (e) {
      error(String(e));
      loading(false);
    }
  }
  return (
    <>
      <div className="heading">
        <div>
          <h1>支付总览</h1>
          <p>查看支付表现，定位成功率变化集中的终端与错误码。</p>
        </div>
        <button className="primary" onClick={start} disabled={busy || !data}>
          <Icon name="sparkles" />
          开始 AI 诊断
        </button>
      </div>
      <section className="filters">
        <Filter
          label="国家 / 地区"
          value={scope.country_code}
          options={countries}
          change={(v) => change("country_code", v)}
        />
        <Filter
          label="支付方式"
          value={scope.payment_method}
          options={{ Klarna: "Klarna", Card: "信用卡", PayPal: "PayPal" }}
          change={(v) => change("payment_method", v)}
        />
        <Filter
          label="终端"
          value={scope.channel || ""}
          options={{
            "": "全部终端",
            Android: "Android",
            Web: "Web",
            iOS: "iOS",
          }}
          change={(v) => change("channel", v)}
        />
        <Filter
          label="分析周期"
          value={scope.period}
          options={{
            "24h": "最近 24 小时",
            "7d": "最近 7 天",
            "30d": "最近 30 天",
          }}
          change={(v) => change("period", v)}
        />
      </section>
      {(err || failed) && <p role="alert">{err || failed}</p>}
      {!data && !failed && <p>正在查询指标…</p>}
      {data && (
        <>
          <div className="cards">
            {[
              ["支付成功率", pct(data[0].psr), "trend"],
              ["较基准期变化", pp(data[1].delta_pp), "activity"],
              [
                "有效支付尝试",
                data[0].valid_attempts.toLocaleString(),
                "credit",
              ],
              ["失败尝试", data[0].failed_attempts.toLocaleString(), "alert"],
            ].map(([name, v, ic]) => (
              <article key={name}>
                <div className="card-label">
                  {name}
                  <Icon name={ic} />
                </div>
                <strong>{v}</strong>
              </article>
            ))}
          </div>
          {data[0].quality_flags.length > 0 && (
            <p className="notice">
              {data[0].valid_attempts === 0
                ? "当前筛选没有有效尝试。"
                : "当前样本少于 30 笔。"}
            </p>
          )}
          <div className="grid">
            <section>
              <h2>支付成功率趋势</h2>
              <p>
                {time(data[0].query_window.start_at)} 至{" "}
                {time(data[0].query_window.end_at)} UTC
              </p>
              <div className="chart" aria-label="窗口内分段成功率">
                {data[4].rows.map((r, i) => (
                  <div
                    className="bar-col"
                    key={r.start_at}
                    title={
                      time(r.start_at) +
                      " UTC · " +
                      pct(r.psr) +
                      " · " +
                      r.valid_attempts +
                      " 笔"
                    }
                  >
                    <span
                      className="bar"
                      style={{ height: (r.psr || 0) * 100 + "%" }}
                    />
                    <small>{i === 0 ? "起点" : i === 11 ? "截止" : ""}</small>
                  </div>
                ))}
              </div>
              <p>
                基准 PSR {pct(data[1].baseline.psr)} ·{" "}
                {data[1].baseline.valid_attempts.toLocaleString()} 笔 ·{" "}
                {time(data[1].baseline.query_window.start_at)} 至{" "}
                {time(data[1].baseline.query_window.end_at)} UTC
              </p>
            </section>
            <section>
              <h2>失败错误分布</h2>
              <p>占所选范围全部失败尝试的比例</p>
              {data[3].rows.map((r) => (
                <div className="error-row" key={r.error_code}>
                  <div>
                    {r.error_code}
                    <b>
                      {r.count} 笔 · {pct(r.share_of_failures)}
                    </b>
                  </div>
                  <progress max={1} value={r.share_of_failures} />
                </div>
              ))}
              {!data[3].rows.length && <p>没有失败记录</p>}
            </section>
          </div>
          <section>
            <h2>终端表现</h2>
            <table>
              <thead>
                <tr>
                  {["终端", "有效尝试", "成功率", "较基准期"].map((x) => (
                    <th key={x}>{x}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data[2].rows.map((r) => (
                  <tr key={r.value}>
                    <td>{r.value}</td>
                    <td>{r.valid_attempts}</td>
                    <td>{pct(r.psr)}</td>
                    <td>{pp(r.delta_pp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p>
              按创建时间单列的其他状态：待决 {data[0].pending}，取消{" "}
              {data[0].cancelled}。
            </p>
          </section>
        </>
      )}
    </>
  );
}
