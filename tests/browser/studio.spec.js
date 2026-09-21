import { test, expect } from "@playwright/test";
const api = "https://api.github.com/repos/sheerazautomate/HeyGen";
const asset =
  "https://github.com/sheerazautomate/HeyGen/releases/download/video-pilot-42/video.mp4";
const release = {
  id: 1,
  tag_name: "video-pilot-42",
  name: "A pro test video <img src=x onerror=alert(1)>",
  published_at: "2026-09-21T10:00:00Z",
  assets: [{ name: "video.mp4", size: 1000000, browser_download_url: asset }],
};
const issue = {
  title: "[Video] My product launch pro",
  body: "HF1.example",
  state: "open",
};
function state(status, message, more = {}) {
  return [
    {
      user: { login: "github-actions[bot]", type: "Bot" },
      body: `<!-- hyperframes-pilot:v1 -->\n\`\`\`json\n${JSON.stringify({ status, message, ...more })}\n\`\`\``,
    },
  ];
}

test.beforeEach(async ({ page }) => {
  await page.route("https://api.github.com/**", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("https://github.com/**", (route) => route.abort());
});

test("example → consent → pro request handoff with quality/fps/format", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("hfgh_token", "obsolete-test-token");
  });
  await page.goto("/");
  await expect(page.getByRole("button", { name: /Prepare pro render/ })).toBeDisabled({ timeout: 5000 });
  await page.getByRole("button", { name: /Try an example/ }).click();
  await expect(page.locator("#file-name")).toHaveText("product-launch.html", { timeout: 10000 });
  await expect(page.locator("#dimensions")).toContainText("1920", { timeout: 10000 });
  await expect(page.locator("#quality")).toBeVisible({ timeout: 5000 });
  await expect(page.locator("#fps")).toBeVisible();
  await expect(page.locator("#format")).toBeVisible();
  await page.locator("#consent").check();
  await page.locator("#quality").selectOption("high");
  await page.locator("#fps").selectOption("60");
  await page.locator("#format").selectOption("webm");
  await page.getByRole("button", { name: /Prepare pro render/ }).click();
  await expect(page.locator("#handoff")).toBeVisible({ timeout: 5000 });
  const packet = await page.locator("#request-packet").inputValue();
  expect(packet.startsWith("HF1.")).toBe(true);
  const decoded = JSON.parse(Buffer.from(packet.slice(4), "base64").toString());
  expect(decoded.private).toBe(true);
  expect(decoded.quality).toBe("high");
  expect(decoded.fps).toBe(60);
  expect(decoded.format).toBe("webm");
  expect(decoded.html).toContain("data-composition-id");
  const link = await page.locator("#submit-request").getAttribute("href");
  expect(link).toContain("template=render-video.yml");
  expect(
    await page.evaluate(() => localStorage.getItem("hfgh_token")),
  ).toBeNull();
});

test("HTML upload is inert, preview works, variables editor appears", async ({
  page,
}) => {
  await page.goto("/");
  const simpleHtml = '<div data-composition-id="main" data-width="1080" data-height="1920" data-duration="3"></div>';
  await page.locator("#file").setInputFiles({
    name: "script.html",
    mimeType: "text/html",
    buffer: Buffer.from(simpleHtml),
  });
  await expect(page.locator("#dimensions")).toContainText("1080", { timeout: 5000 });
  await expect(page.locator("#preview-wrap")).toBeVisible({ timeout: 5000 });

  const htmlWithVars = `<div data-composition-id="main" data-width="1080" data-height="1920" data-duration="3" data-composition-variables='[{"id":"headline","label":"Headline","type":"string","default":"Hello"}]'></div>`;
  await page.locator("#remove-file").click();
  await page.locator("#file").setInputFiles({
    name: "vars.html",
    mimeType: "text/html",
    buffer: Buffer.from(htmlWithVars),
  });
  await expect(page.locator("#variables-card")).toBeVisible({ timeout: 5000 });
  await expect(page.locator("#variables-list input")).toHaveCount(1, { timeout: 3000 });

  await page.locator("#remove-file").click();
  await page.locator("#file").setInputFiles({
    name: "not-html.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("bad"),
  });
  await expect(page.locator("#file-message")).toContainText(".html", { timeout: 3000 });
});

test("clipboard denied has a usable manual-copy fallback", async ({ page }) => {
  await page.addInitScript(() =>
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: () => Promise.reject(new Error("denied")) },
    }),
  );
  await page.goto("/");
  await page.locator("#load-example").click();
  await expect(page.locator("#file-name")).toHaveText("product-launch.html", { timeout: 10000 });
  await page.locator("#consent").check();
  await page.locator("#prepare").click();
  await page.locator("#copy-request").click();
  await expect(page.locator("#request-packet")).toBeVisible({ timeout: 5000 });
  await expect(page.locator("#copy-message")).toContainText("Clipboard", { timeout: 3000 });
});

test("gallery has a useful empty state and renders release titles as text", async ({
  page,
}) => {
  await page.goto("/#gallery");
  await expect(page.locator("#gallery-empty")).toBeVisible({ timeout: 5000 });
  await page.route(`${api}/releases?*`, (route) =>
    route.fulfill({ json: [release] }),
  );
  await page.locator("#refresh-gallery").click();
  await expect(page.locator(".video-card h3")).toHaveText(release.name, { timeout: 5000 });
  await expect(page.locator(".video-card video")).toHaveAttribute("src", asset, { timeout: 5000 });
});

test("tracking checks issue, bot status, video, and browser history", async ({
  page,
}) => {
  await page.route(`${api}/issues/42`, (route) =>
    route.fulfill({ json: issue }),
  );
  await page.route(`${api}/issues/42/comments?*`, (route) =>
    route.fulfill({
      json: state("ready", "Your pro video is ready.", { tag: "video-pilot-42" }),
    }),
  );
  await page.route(`${api}/releases/tags/video-pilot-42`, (route) =>
    route.fulfill({ json: release }),
  );
  await page.goto("/#track/42");
  await expect(page.locator("#tracking-status")).toContainText("Ready", { timeout: 10000 });
  await expect(page.locator("#tracking-video video")).toHaveAttribute("src", asset, { timeout: 10000 });
  await expect(page.locator("#recent-requests")).toContainText("Request #42", { timeout: 5000 });
  await page.locator("#clear-history").click();
  await expect(page.locator("#recent-requests")).toHaveText("No pro requests tracked yet.", { timeout: 3000 });
});

test("failed and rejected renders explain what to do", async ({ page }) => {
  await page.route(`${api}/issues/42`, (route) =>
    route.fulfill({ json: issue }),
  );
  await page.route(`${api}/issues/42/comments?*`, (route) =>
    route.fulfill({
      json: state("rejected", "Pro render failed."),
    }),
  );
  await page.goto("/#track/42");
  await expect(page.locator("#tracking-status")).toContainText("Not accepted", { timeout: 10000 });
  await expect(page.locator("#tracking-detail")).toContainText("Pro render", { timeout: 5000 });
});

test("foreign issues and rate limiting show actionable errors", async ({
  page,
}) => {
  await page.goto("/#track");
  await page.locator("#request-link").fill("https://github.com/other/repo/issues/42");
  await page.locator("#track-request").click();
  await expect(page.locator("#track-message")).toContainText("this studio", { timeout: 5000 });
  await page.route(`${api}/issues/42`, (route) =>
    route.fulfill({ status: 403, json: { message: "rate limit" } }),
  );
  await page.locator("#request-link").fill("42");
  await page.locator("#track-request").click();
  await expect(page.locator("#track-message")).toContainText("API limit", { timeout: 10000 });
});

test("mobile navigation and workspace do not overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator("#view-create")).toBeVisible({ timeout: 5000 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 10),
  ).toBe(true);
  await page.getByRole("link", { name: /Private gallery/i }).click();
  await expect(page.locator("#view-gallery")).toBeVisible({ timeout: 5000 });
});
