import { test, expect, Page } from "@playwright/test";
async function ask(p: Page, q: string) {
  await p.goto("/diagnoses");
  await p.getByLabel("诊断问题").fill(q);
  await p.getByRole("button", { name: "发送" }).click();
}
async function golden(p: Page) {
  await p.goto("/dashboard");
  await expect(p.getByText("89.2%", { exact: true })).toBeVisible();
  await p.getByRole("button", { name: "开始 AI 诊断" }).click();
  await p.getByRole("link", { name: "查看完整报告" }).click();
}
for (let i = 1; i <= 3; i++)
  test("黄金报告连续回放 " + i, async ({ page }) => {
    await golden(page);
    await expect(page.getByText("89.2%", { exact: true })).toBeVisible();
    await expect(page.getByText(/90\/150/)).toBeVisible();
    await expect(page.getByText(/Android 回跳链路值得优先排查/)).toBeVisible();
  });
test("筛选传递与刷新", async ({ page }) => {
  await page.goto("/dashboard");
  await page.getByLabel("终端", { exact: true }).selectOption("Web");
  await page.reload();
  await page.getByRole("button", { name: "开始 AI 诊断" }).click();
  await page.getByRole("link", { name: "查看完整报告" }).click();
  await expect(page.getByText("93.4%", { exact: true })).toBeVisible();
});
test("澄清恢复", async ({ page }) => {
  await ask(page, "分析成功率");
  await page.getByLabel("补充条件").fill("德国 Klarna");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByRole("link", { name: "查看完整报告" })).toBeVisible();
});
test("查看真实引用", async ({ page }) => {
  await ask(page, "解释 redirect_timeout 含义");
  await page.getByRole("link", { name: "查看完整报告" }).click();
  await page.locator("summary").filter({ hasText: "KB-002" }).first().click();
  await expect(page.locator("details[open] small")).toContainText("kb-v1");
});
test("版本追问保留会话", async ({ page }) => {
  await golden(page);
  await page.getByRole("link", { name: "继续追问" }).click();
  await page.getByLabel("继续追问").fill("是否与 Android 版本发布有关");
  await page.getByRole("button", { name: "发送" }).click();
  await page.getByRole("link", { name: "查看完整报告" }).click();
  await expect(page.getByText(/条演示发布记录/)).toBeVisible();
  await expect(page.getByText(/无法确认具体 SDK/)).toBeVisible();
});
test("无知识覆盖", async ({ page }) => {
  await ask(page, "解释量子纠缠");
  await expect(page.getByText("知识库没有匹配此问题的来源。")).toBeVisible();
});
test("无有效样本", async ({ page }) => {
  await ask(page, "德国 Klarna iOS 的支付表现");
  await expect(page.getByText(/低于 30 笔/)).toBeVisible();
});
test("取消持久化", async ({ page }) => {
  await ask(page, "成功率下降");
  await page.getByRole("button", { name: "停止执行" }).click();
  await page.reload();
  await expect(page.getByText("已取消", { exact: true })).toBeVisible();
});
test("刷新复用任务", async ({ page }) => {
  await ask(page, "分析德国 Klarna");
  await expect(page.getByRole("link", { name: "查看完整报告" })).toBeVisible();
  const id = page.url();
  await page.reload();
  await expect(page).toHaveURL(id);
  await expect(page.getByRole("link", { name: "查看完整报告" })).toBeVisible();
});
test("报告反馈", async ({ page }) => {
  await golden(page);
  await page.getByLabel("备注").fill("可复算");
  await page.getByRole("button", { name: "提交反馈" }).click();
  await expect(page.getByText("反馈已保存")).toBeVisible();
});
test("拒绝支付写入", async ({ page }) => {
  await ask(page, "直接切换支付渠道");
  await expect(page.getByText(/本次请求已拒绝/)).toBeVisible();
});
test("移动端知识库", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "导航菜单" }).click();
  await page.getByRole("link", { name: "知识库" }).click();
  await page.getByLabel("检索文档").fill("WebView");
  await expect(page.locator("summary").first()).toContainText("KB-001");
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});
