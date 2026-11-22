// Four scripted browser sessions. All observations come from visible controls,
// dashboard cards, or report evidence expanded by the scripted participant.
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { chromium } from "@playwright/test";
import { createServer } from "vite";

const api = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(api || ""))
  throw Error("Use evaluation/study.py pilot");
const root = path.resolve(import.meta.dirname, "..");
const archives = path.join(root, "../evaluation/results/experiments");
const roles = ["轮值运营", "支付分析师", "发布质量工程师", "商户支持"];
// Raw counts independently counted from the fixed seed, before browser runs.
const metrics = [
  {
    c: "DE",
    m: "Klarna",
    ch: "Web",
    p: "24h",
    n: 1000,
    s: 934,
    bn: 2000,
    bs: 1900,
  },
  { c: "GB", m: "Card", ch: "Web", p: "7d", n: 843, s: 777, bn: 125, bs: 113 },
];
const errors = [
  {
    c: "DE",
    m: "Klarna",
    ch: "Android",
    p: "24h",
    code: "redirect_timeout",
    count: 90,
    failed: 150,
  },
  {
    c: "SG",
    m: "PayPal",
    ch: "iOS",
    p: "7d",
    code: "issuer_declined",
    count: 25,
    failed: 44,
  },
];
const pct = (n, d) => ((n / d) * 100).toFixed(1) + "%";
const num = (s) => Number(s.replaceAll(",", ""));
const records = [];

async function send(page, label, q, log) {
  log.push({ action: label, text: q });
  await page.getByLabel(label, { exact: true }).fill(q);
  await Promise.all([
    page.waitForEvent("domcontentloaded"),
    page.getByRole("button", { name: "发送" }).click(),
  ]);
}

async function openReport(page, log) {
  const link = page.getByRole("link", { name: "查看完整报告" });
  const stop = page
    .locator(".pill")
    .filter({ hasText: /等待补充条件|无法判定|执行失败|已取消/ });
  await link.or(stop).first().waitFor();
  if (!(await link.isVisible()))
    throw Error(
      "诊断停在" +
        (await stop.innerText()) +
        " " +
        (await page.locator(".notice").innerText()),
    );
  await link.click();
  await page.getByRole("heading", { name: "数据证据" }).waitFor();
  log.push({ action: "打开报告", path: new URL(page.url()).pathname });
}
async function evidence(page, key, log) {
  const detail = page
    .locator("details")
    .filter({ has: page.getByText(key, { exact: true }) });
  await detail.locator("summary").click();
  log.push({ action: "展开证据", key });
  return JSON.parse(await detail.locator("pre").innerText());
}
async function card(page, label) {
  return page
    .locator("article")
    .filter({ has: page.getByText(label, { exact: true }) })
    .locator("strong")
    .innerText();
}
async function readDashboard(page, kind, a, log) {
  await page.goto("/dashboard");
  for (const [label, value] of [
    ["国家 / 地区", a.c],
    ["支付方式", a.m],
    ["终端", a.ch],
    ["分析周期", a.p],
  ]) {
    await page.getByLabel(label, { exact: true }).selectOption(value);
    log.push({ action: label, value });
  }
  if (kind === "查数") {
    const baseline = await page.getByText(/^基准 PSR /).innerText();
    return {
      valid: num(await card(page, "有效支付尝试")),
      psr: await card(page, "支付成功率"),
      baseline: baseline.match(/基准 PSR (\S+)/)[1],
    };
  }
  const first = page.locator(".error-row").first();
  const amounts = await first.locator("b").innerText();
  const match = amounts.match(/(\d+) 笔 · ([\d.]+%)/);
  return {
    code: (await first.innerText()).replace(amounts, "").trim(),
    count: Number(match[1]),
    failed: num(await card(page, "失败尝试")),
    share: match[2],
  };
}
async function readAI(page, kind, a, actor, log) {
  const country = { DE: "德国", GB: "英国", SG: "新加坡" }[a.c];
  const terminal = actor === 3 && kind === "查数" ? "网页端" : a.ch;
  const ask =
    kind === "查数"
      ? "报一下笔数、当前和基准成功率"
      : "查占比最高的错误码，附失败分母";
  await page.goto("/diagnoses");
  await send(
    page,
    "诊断问题",
    country + " " + a.m + " " + terminal + " 最近" + a.p + "，" + ask + "。",
    log,
  );
  await openReport(page, log);
  if (kind === "查数") {
    const ev = await evidence(page, "get_payment_metrics", log);
    log.push({ observed_filters: ev.filters });
    return {
      valid: num(await card(page, "有效尝试")),
      psr: await card(page, "当前成功率"),
      baseline: await card(page, "基准成功率"),
    };
  }
  const ev = await evidence(page, "get_error_distribution", log);
  log.push({ observed_filters: ev.filters });
  const first = ev.rows[0];
  return {
    code: first.error_code,
    count: first.count,
    failed: ev.failed_attempts,
    share: pct(first.count, ev.failed_attempts),
  };
}
const journeys = [
  {
    title: "遇到不支持的周期后补充条件",
    expected: { sameTask: true, period: "7d", valid: 829 },
    async run(page, log) {
      await page.goto("/diagnoses");
      await send(
        page,
        "诊断问题",
        "英国 Klarna Android，先取最近48小时。",
        log,
      );
      await page.getByLabel("补充条件").waitFor();
      const original = new URL(page.url()).pathname;
      log.push({ notice: await page.locator(".notice").innerText() });
      await send(page, "补充条件", "那就按最近七天。", log);
      await openReport(page, log);
      const ev = await evidence(page, "get_payment_metrics", log);
      const link = await page
        .getByRole("link", { name: "继续追问" })
        .getAttribute("href");
      return {
        sameTask: link === original,
        period: ev.filters.period,
        valid: ev.valid_attempts,
      };
    },
  },
  {
    title: "找到分母定义和原始出处",
    expected: {
      doc: "KB-003",
      pending: true,
      cancelled: true,
      version: "kb-v1",
    },
    async run(page, log) {
      await page.goto("/knowledge");
      await page.getByLabel("检索文档").fill("PENDING");
      log.push({ action: "检索文档", text: "PENDING" });
      const doc = page.locator("details").filter({
        has: page.locator("summary").filter({ hasText: "分母与成熟窗口" }),
      });
      await doc.locator("summary").click();
      const content = await doc.locator("p").innerText();
      const source = await doc.locator("small").innerText();
      log.push({ source, content });
      return {
        doc: (await doc.locator("summary").innerText()).split(" · ")[0],
        pending: content.includes("PENDING"),
        cancelled: content.includes("CANCELLED"),
        version: source.split(" · ")[1],
      };
    },
  },
  {
    title: "从看板追问发布记录并核实归因边界",
    expected: {
      record: "demo-release-2.5",
      channel: "Android",
      uncertain: true,
    },
    async run(page, log) {
      await page.goto("/dashboard");
      await page.getByLabel("终端", { exact: true }).selectOption("Android");
      await page.getByRole("button", { name: "开始 AI 诊断" }).click();
      log.push({ action: "看板发起 Android 诊断" });
      await openReport(page, log);
      await page.getByRole("link", { name: "继续追问" }).click();
      await send(page, "继续追问", "这次与 Android 版本发布有关吗？", log);
      await openReport(page, log);
      const ev = await evidence(page, "get_release_changes", log);
      return {
        record: ev.rows[0]?.release_id,
        channel: ev.filters.channel,
        uncertain: await page.getByText(/无法确认具体 SDK/).isVisible(),
      };
    },
  },
  {
    title: "空样本后切换到有数据的支付方式",
    expected: { zero: true, method: "PayPal", valid: 845 },
    async run(page, log) {
      await page.goto("/diagnoses");
      await send(page, "诊断问题", "新加坡 Klarna，iOS 最近7天有多少笔？", log);
      const notice = await page.getByText(/低于 30 笔/).innerText();
      log.push({ notice });
      await send(
        page,
        "继续追问",
        "改查新加坡 PayPal，仍看 iOS 最近七天。",
        log,
      );
      await openReport(page, log);
      const ev = await evidence(page, "get_payment_metrics", log);
      return {
        zero: notice.includes("尝试 0 笔"),
        method: ev.filters.payment_method,
        valid: ev.valid_attempts,
      };
    },
  },
];

async function attempt(page, assignment, run) {
  const steps = [];
  const start = performance.now();
  const result = {
    ...assignment,
    order: records.filter((r) => r.actor === assignment.actor).length + 1,
    steps,
    passed: false,
  };
  try {
    result.observed = await run(steps);
    result.passed = isDeepStrictEqual(result.observed, assignment.expected);
  } catch (error) {
    result.error = String(error.message).split("Call log:")[0].trim();
  }
  result.seconds = Number(((performance.now() - start) / 1000).toFixed(3));
  result.path = new URL(page.url()).pathname;
  records.push(result);
}

await mkdir(archives, { recursive: true });
const out = await mkdtemp(path.join(archives, "pilot-browser-"));
const server = await createServer({
  root,
  server: { host: "127.0.0.1", port: 0, proxy: { "/api": api } },
  logLevel: "error",
});
let browser;
try {
  await server.listen();
  const health = await fetch(api + "/api/health", {
    signal: AbortSignal.timeout(10000),
  });
  if ((await health.json()).llm_provider !== "rules")
    throw Error("pilot requires the rules fixture");
  const baseURL = "http://127.0.0.1:" + server.httpServer.address().port;
  browser = await chromium.launch({
    channel: process.env.PLAYWRIGHT_CHANNEL || "chrome",
  });
  for (const [i, role] of roles.entries()) {
    const actor = "sim-0" + (i + 1);
    const context = await browser.newContext({ baseURL });
    const page = await context.newPage();
    page.setDefaultTimeout(7000);
    try {
      for (const [k, kind] of ["查数", "核对错误分母"].entries()) {
        for (const turn of [0, 1]) {
          const ai = (turn + i + k) % 2 === 1;
          // Cross order and case version independently so both routes see each variant twice.
          const v = (turn + Math.floor(i / 2) + k) % 2;
          const a = (k === 0 ? metrics : errors)[v];
          const expected =
            k === 0
              ? { valid: a.n, psr: pct(a.s, a.n), baseline: pct(a.bs, a.bn) }
              : {
                  code: a.code,
                  count: a.count,
                  failed: a.failed,
                  share: pct(a.count, a.failed),
                };
          await attempt(
            page,
            {
              actor,
              role,
              kind,
              variant: v + 1,
              method: ai ? "AI 诊断" : "看板",
              expected,
            },
            (log) =>
              ai
                ? readAI(page, kind, a, i, log)
                : readDashboard(page, kind, a, log),
          );
        }
      }
      const journey = journeys[i];
      await attempt(
        page,
        {
          actor,
          role,
          kind: journey.title,
          method: "专项流程",
          expected: journey.expected,
        },
        (log) => journey.run(page, log),
      );
    } finally {
      await context.close();
    }
  }
  const summary = {
    mode: "scripted-browser",
    provider: "rules",
    browser: browser.version(),
    actors: roles.length,
    total: records.length,
    passed: records.filter((r) => r.passed).length,
  };
  await writeFile(
    path.join(out, "sessions.jsonl"),
    records.map((r) => JSON.stringify(r) + "\n").join(""),
  );
  await writeFile(
    path.join(out, "summary.json"),
    JSON.stringify(summary, null, 2) + "\n",
  );
  console.log(out, summary);
  process.exitCode = Number(summary.passed !== summary.total);
} finally {
  await browser?.close();
  await server.close();
}
