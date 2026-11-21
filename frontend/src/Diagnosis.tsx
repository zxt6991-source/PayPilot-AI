import { useEffect, useState } from "react";
import {
  api,
  useResource,
  pct,
  pp,
  Run,
  Accepted,
  states,
  paused,
} from "./api";
import { Icon } from "./Dashboard";

function remember(r: Run) {
  sessionStorage.setItem("task", r.task_id);
  if (r.report) sessionStorage.setItem("report", r.report.report_id);
}

export function Diagnosis({ tid }: { tid?: string }) {
  const [run, set] = useState<Run>(),
    [question, input] = useState(""),
    [notice, msg] = useState(""),
    [busy, loading] = useState(false);
  useEffect(() => {
    if (!tid) return;
    let active = true,
      source: EventSource | undefined,
      latest = 0;
    async function refresh() {
      const ticket = ++latest;
      const next = await api<Run>("diagnoses/" + tid);
      if (!active || ticket !== latest) return;
      remember(next);
      set(next);
      msg("");
      if (paused(next.state)) {
        source?.close();
        return;
      }
      if (!source) {
        const cursor = next.events.at(-1)?.sequence || 0;
        source = new EventSource(
          `/api/diagnoses/${tid}/events?run_id=${next.run_id}&after=${cursor}`,
        );
        const update = () =>
          refresh().catch((e) => {
            if (active) msg(String(e));
          });
        for (const event of [
          "step.started",
          "tool.completed",
          "clarification.required",
          "report.ready",
          "run.failed",
          "run.insufficient_data",
          "run.cancelled",
        ])
          source.addEventListener(event, update);
        source.onerror = () => {
          if (active) {
            msg("连接中断，正在恢复任务状态…");
            update();
          }
        };
      }
    }
    refresh().catch((e) => {
      if (active) msg(String(e));
    });
    return () => {
      active = false;
      source?.close();
    };
  }, [tid]);
  async function submit(text: string) {
    if (!text.trim()) return;
    loading(true);
    msg("");
    try {
      const path = tid ? "diagnoses/" + tid + "/messages" : "diagnoses";
      const t = await api<Accepted>(
        path,
        { question: text, ...(run ? { run_id: run.run_id } : {}) },
        crypto.randomUUID(),
      );
      location.assign("/diagnoses/" + t.task_id);
    } catch (e) {
      msg(String(e));
      loading(false);
    }
  }
  async function stop() {
    if (!run) return;
    loading(true);
    try {
      await api("diagnoses/" + tid + "/cancel", { run_id: run.run_id });
      location.reload();
    } catch (e) {
      msg(String(e));
      loading(false);
    }
  }
  return (
    <>
      <div className="heading">
        <div>
          <h1>AI 智能诊断</h1>
          <p>输入支付分析问题，或补充当前任务的诊断范围。</p>
        </div>
        {tid && (
          <a className="button" href="/diagnoses">
            新建诊断
          </a>
        )}
      </div>
      {run && (
        <section>
          <div className="line">
            <h2>{run.question}</h2>
            <span className="pill">{states[run.state]}</span>
          </div>
          <p>
            {[
              run.filters.country_code,
              run.filters.payment_method,
              run.filters.channel,
              run.filters.period,
              run.model_id,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {run.reason && <p className="notice">{run.reason}</p>}
          <ol className="timeline">
            {run.events
              .filter((e) =>
                ["step.started", "tool.completed"].includes(e.event_type),
              )
              .map((e) => (
                <li key={e.sequence}>
                  {e.payload.tool || states[e.payload.state || ""]}
                </li>
              ))}
          </ol>
          {run.report && (
            <a
              className="button primary"
              href={"/reports/" + run.report.report_id}
            >
              查看完整报告 <Icon name="arrow" />
            </a>
          )}
          {(!paused(run.state) || run.state === "CLARIFYING") && (
            <button onClick={stop} disabled={busy}>
              停止执行
            </button>
          )}
          {["FAILED", "CANCELLED"].includes(run.state) && (
            <button onClick={() => submit(run.question)} disabled={busy}>
              重新诊断
            </button>
          )}
        </section>
      )}
      {(!tid || (run && paused(run.state))) && (
        <section>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(question);
            }}
          >
            <label>
              {run?.state === "CLARIFYING"
                ? "补充条件"
                : run
                  ? "继续追问"
                  : "诊断问题"}
              <textarea
                required
                maxLength={1500}
                value={question}
                onChange={(e) => input(e.target.value)}
                placeholder="例如：分析德国 Klarna 最近 24 小时支付成功率下降的原因"
              />
            </label>
            <button className="primary" disabled={busy || !question.trim()}>
              <Icon name="send" />
              发送
            </button>
          </form>
        </section>
      )}
      <p role="status">{notice}</p>
    </>
  );
}

export function ReportPage({ id }: { id?: string }) {
  const { data: r, error } = useResource(id || "", async () =>
    id ? api<Run>("reports/" + id) : undefined,
  );
  const [feedback, setFeedback] = useState("helpful"),
    [note, setNote] = useState(""),
    [status, setStatus] = useState(""),
    [saving, setSaving] = useState(false);
  const report = r?.report;
  if (!report || !r)
    return (
      <>
        <h1>诊断报告</h1>
        <p>
          {error || (id ? "正在读取…" : "完成一次诊断后即可在此查看报告。")}
        </p>
        <a className="button" href="/diagnoses">
          进入诊断
        </a>
      </>
    );
  async function send() {
    if (!r || !report) return;
    setSaving(true);
    try {
      await api("diagnoses/" + r.task_id + "/feedback", {
        run_id: r.run_id,
        report_id: report.report_id,
        rating: feedback,
        note,
      });
      setStatus("反馈已保存");
    } catch (e) {
      setStatus(String(e));
      setSaving(false);
    }
  }
  const hits = r.evidence.flatMap((e) => e.payload.hits || []);
  function exportReport() {
    if (!r || !report) return;
    const body = [
      "# PayPilot AI · DEMO 诊断报告",
      r.question,
      JSON.stringify(report.scope),
      ...(report.metrics
        ? [
            "当前 PSR " +
              pct(report.metrics.current_psr) +
              "，基准 PSR " +
              pct(report.metrics.baseline_psr) +
              "，变化 " +
              pp(report.metrics.delta_pp),
          ]
        : []),
      "## 观察",
      ...report.findings.map((f) => f.text + " " + f.evidence_ids.join(", ")),
      "## 待验证假设",
      ...report.hypotheses.map((f) => f.text),
      "## 核查建议",
      ...report.actions,
      "## 不确定性",
      ...report.uncertainties,
      "## 知识引用",
      ...hits.map(
        (h) =>
          h.chunk_id + " · " + h.title + " / " + h.location + " — " + h.content,
      ),
    ].join("\n\n");
    const url = URL.createObjectURL(
      new Blob([body], { type: "text/markdown;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = report.report_id + ".md";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <>
      <div className="heading">
        <div>
          <h1>诊断报告</h1>
          <p>
            {r.question} · {r.workflow_version}
          </p>
        </div>
        <button onClick={exportReport}>
          <Icon name="download" />
          导出 Markdown
        </button>
      </div>
      {report.metrics && (
        <div className="cards">
          {[
            ["当前成功率", pct(report.metrics.current_psr)],
            ["基准成功率", pct(report.metrics.baseline_psr)],
            ["变化", pp(report.metrics.delta_pp)],
            ["有效尝试", report.metrics.valid_attempts],
          ].map(([k, v]) => (
            <article key={k}>
              <div className="card-label">{k}</div>
              <strong>{v}</strong>
            </article>
          ))}
        </div>
      )}
      <section>
        <h2>观察事实</h2>
        {report.findings.map((f, i) => (
          <p key={i}>
            {f.text} <a href={"#" + f.evidence_ids[0]}>查看证据</a>
          </p>
        ))}
        <h2>待验证假设</h2>
        {report.hypotheses.length ? (
          report.hypotheses.map((h, i) => (
            <p key={i}>
              {h.text} <a href={"#" + h.evidence_ids[0]}>查看证据</a>
            </p>
          ))
        ) : (
          <p>缺少可支持进一步归因的证据。</p>
        )}
        <h2>核查建议</h2>
        {report.actions.map((x) => (
          <p key={x}>{x}</p>
        ))}
        <h2>不确定性</h2>
        {report.uncertainties.map((x) => (
          <p key={x}>{x}</p>
        ))}
      </section>
      <section>
        <h2>知识引用</h2>
        {hits.map((h) => (
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
        {!hits.length && <p>没有匹配的知识条目。</p>}
      </section>
      <section>
        <h2>数据证据</h2>
        {r.evidence.map((e) => (
          <details id={e.evidence_id} key={e.evidence_id}>
            <summary>{e.source_key}</summary>
            <pre>{JSON.stringify(e.payload, null, 2)}</pre>
          </details>
        ))}
      </section>
      <section>
        <h2>报告反馈</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <label>
            这份报告有帮助吗？
            <select
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
            >
              <option value="helpful">有帮助</option>
              <option value="unhelpful">需要改进</option>
            </select>
          </label>
          <label>
            备注
            <textarea
              maxLength={1000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <div className="line">
            <button disabled={saving}>提交反馈</button>
            <a href={"/diagnoses/" + r.task_id}>继续追问 →</a>
          </div>
          <p role="status">{status}</p>
        </form>
      </section>
    </>
  );
}
