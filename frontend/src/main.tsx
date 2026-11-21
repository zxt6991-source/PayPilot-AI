import { useState } from "react";
import { createRoot } from "react-dom/client";
import { Dashboard, Icon } from "./Dashboard";
import { Diagnosis, ReportPage } from "./Diagnosis";
import { api, useResource, Chunk, time } from "./api";
import "./style.css";

function Knowledge() {
  const [q, set] = useState("");
  const { data, error } = useResource(q, () =>
    api<Chunk[]>("knowledge?q=" + encodeURIComponent(q)),
  );
  return (
    <>
      <h1>知识库</h1>
      <p>项目自编的演示知识与排查说明</p>
      <section>
        <label>
          检索文档
          <input
            type="search"
            placeholder="输入错误码、PSR 或 WebView"
            value={q}
            onChange={(e) => set(e.target.value)}
          />
        </label>
        {error && <p role="alert">{error}</p>}
        {data?.map((h) => (
          <details key={h.chunk_id}>
            <summary>
              {h.document_id} · {h.title} / {h.location}
            </summary>
            <p>{h.content}</p>
            <small>
              {h.source} · {h.version} · {h.chunk_id}
            </small>
          </details>
        ))}
        {data?.length === 0 && <p>未找到匹配来源</p>}
      </section>
    </>
  );
}
type Summary = {
  split: string;
  total: number;
  passed: number;
  p95_seconds: number;
  model_id: string;
  workflow_version: string;
  generated_at: string;
  categories: Record<string, { passed: number; total: number }>;
};
function Evaluation() {
  const { data, error } = useResource("eval", () =>
    api<{ results: Summary[] }>("evaluation"),
  );
  return (
    <>
      <h1>评测中心</h1>
      <p>固定模拟数据上的自动化回归记录</p>
      {error && <p role="alert">{error}</p>}
      {data?.results.length === 0 && <section>尚未运行离线评测。</section>}
      {data?.results.map((s) => (
        <section key={s.split}>
          <h2>
            {s.split === "dev" ? "开发集" : "留出集"} · {s.passed}/{s.total}{" "}
            例通过
          </h2>
          <p>
            {s.model_id} · {s.workflow_version} · P95 {s.p95_seconds} 秒 ·{" "}
            {time(s.generated_at)} UTC
          </p>
          <table>
            <thead>
              <tr>
                <th>类别</th>
                <th>通过</th>
                <th>总数</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.categories).map(([k, v]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td>{v.passed}</td>
                  <td>{v.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </>
  );
}
const nav = [
  ["dashboard", "支付总览", "dashboard"],
  ["diagnoses", "AI 智能诊断", "sparkles"],
  ["reports", "诊断报告", "report"],
  ["knowledge", "知识库", "library"],
  ["evaluation", "评测中心", "flask"],
];
function App() {
  const [, path = "dashboard", id] = location.pathname.split("/"),
    page = path || "dashboard";
  const name = nav.find((x) => x[0] === page)?.[1];
  const { data } = useResource("health", () =>
    api<{ as_of_utc: string }>("health"),
  );
  const [menu, show] = useState(false);
  function href(p: string) {
    const key = p === "diagnoses" ? "task" : p === "reports" ? "report" : null;
    return (
      "/" +
      p +
      (key && sessionStorage.getItem(key)
        ? "/" + sessionStorage.getItem(key)
        : "")
    );
  }
  return (
    <div className="shell">
      <aside className={menu ? "open" : ""}>
        <div className="brand">
          <i>P</i>
          <div>
            PayPilot AI<small>支付诊断工作台</small>
          </div>
        </div>
        <nav>
          {nav.map(([p, n, ic]) => (
            <a key={p} className={p === page ? "active" : ""} href={href(p)}>
              <Icon name={ic} />
              {n}
            </a>
          ))}
        </nav>
        <div className="safety">
          <Icon name="shield" />
          只读演示环境
        </div>
      </aside>
      <main>
        <header>
          <div>
            <button
              className="menu"
              aria-label="导航菜单"
              onClick={() => show(!menu)}
            >
              <Icon name="menu" />
            </button>
            PayPilot AI　/　<b>{name}</b>
          </div>
          <span className="badge">●　DEMO DATA</span>
        </header>
        <div className="content">
          <div className="snapshot">
            {data
              ? "数据快照 · " + time(data.as_of_utc) + " UTC"
              : "正在连接数据服务"}
          </div>
          {page === "dashboard" ? (
            <Dashboard />
          ) : page === "diagnoses" ? (
            <Diagnosis tid={id} />
          ) : page === "reports" ? (
            <ReportPage id={id} />
          ) : page === "knowledge" ? (
            <Knowledge />
          ) : page === "evaluation" ? (
            <Evaluation />
          ) : (
            <p>
              页面不存在 · <a href="/dashboard">返回支付总览</a>
            </p>
          )}
        </div>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
