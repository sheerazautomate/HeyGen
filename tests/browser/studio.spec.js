import { test, expect } from "@playwright/test";
const api = "https://api.github.com/repos/sheerazautomate/HeyGen";
const asset =
  "https://github.com/sheerazautomate/HeyGen/releases/download/video-pilot-42/video.mp4";
const release = {
  id: 1,
  tag_name: "video-pilot-42",
  name: "A test video <img src=x onerror=alert(1)>",
  published_at: "2026-09-21T10:00:00Z",
  assets: [{ name: "video.mp4", size: 1000000, browser_download_url: asset }],
};
const issue = {
  title: "[Video] My product launch",
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

test("example → consent → request handoff; no tokens or direct dispatch", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => {
    localStorage.setItem("hfgh_token", "obsolete-test-token");
  });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Prepare my video" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: /Try an example/ }).click();
  await expect(page.locator("#file-name")).toHaveText("product-launch.html");
  await expect(page.locator("#dimensions")).toHaveText("1920 × 1080");
  await page.locator("#consent").check();
  await page.getByRole("button", { name: "Prepare my video" }).click();
  const packet = await page.locator("#request-packet").inputValue();
  const decoded = JSON.parse(Buffer.from(packet.slice(4), "base64").toString());
  expect(decoded.public).toBe(true);
  expect(decoded.html).toContain("data-composition-id");
  const link = await page.locator("#submit-request").getAttribute("href");
  expect(link).toContain("template=render-video.yml");
  expect(link.length).toBeLessThan(500);
  await page.locator("#title").fill("A changed title");
  await expect(page.locator("#handoff")).toBeHidden();
  expect(
    await page.evaluate(() => localStorage.getItem("hfgh_token")),
  ).toBeNull();
  expect(errors).toEqual([]);
});

test("HTML upload is inert, can be removed, and invalid input clears old files", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .locator("#file")
    .setInputFiles({
      name: "script.html",
      mimeType: "text/html",
      buffer: Buffer.from(
        '<div data-composition-id="main" data-width="1080" data-height="1920" data-duration="3"></div><script>window.uploadExecuted = true;</script>',
      ),
    });
  await expect(page.locator("#dimensions")).toHaveText("1080 × 1920");
  expect(await page.evaluate(() => window.uploadExecuted)).toBeUndefined();
  await page.locator("#remove-file").click();
  await page
    .locator("#file")
    .setInputFiles({
      name: "not-html.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("bad"),
    });
  await expect(page.locator("#file-message")).toContainText(".html");
  await expect(page.locator("#prepare")).toBeDisabled();
});

test("clipboard denied has a usable manual-copy fallback", async ({ page }) => {
  await page.addInitScript(() =>
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: () => Promise.reject(new Error("denied")) },
    }),
  );
  await page.goto("/");
  await page.locator("#load-example").click();
  await page.locator("#consent").check();
  await page.locator("#prepare").click();
  await page.locator("#copy-request").click();
  await expect(page.locator("#request-packet")).toBeVisible();
  await expect(page.locator("#copy-message")).toContainText(
    "Clipboard access is blocked",
  );
});

test("gallery has a useful empty state and renders release titles as text", async ({
  page,
}) => {
  await page.goto("/#gallery");
  await expect(page.locator("#gallery-empty")).toBeVisible();
  await page.route(`${api}/releases?*`, (route) =>
    route.fulfill({ json: [release] }),
  );
  await page.locator("#refresh-gallery").click();
  await expect(page.locator(".video-card h3")).toHaveText(release.name);
  await expect(page.locator(".video-card img")).toHaveCount(0);
  await expect(page.locator(".video-card video")).toHaveAttribute("src", asset);
});

test("tracking checks issue, bot status, video, and browser history", async ({
  page,
}) => {
  await page.route(`${api}/issues/42`, (route) =>
    route.fulfill({ json: issue }),
  );
  await page.route(`${api}/issues/42/comments?*`, (route) =>
    route.fulfill({
      json: state("ready", "Your video is ready.", { tag: "video-pilot-42" }),
    }),
  );
  await page.route(`${api}/releases/tags/video-pilot-42`, (route) =>
    route.fulfill({ json: release }),
  );
  await page.goto("/#track/42");
  await expect(page.locator("#tracking-status")).toHaveText("Ready");
  await expect(page.locator("#tracking-video video")).toHaveAttribute(
    "src",
    asset,
  );
  await expect(page.locator("#recent-requests")).toContainText("Request #42");
  await page.reload();
  await expect(page.locator("#tracking-video video")).toBeVisible();
  await page.locator("#clear-history").click();
  await expect(page.locator("#recent-requests")).toHaveText(
    "No requests tracked yet.",
  );
});

test("failed and rejected renders explain what to do", async ({ page }) => {
  await page.route(`${api}/issues/42`, (route) =>
    route.fulfill({ json: issue }),
  );
  await page.route(`${api}/issues/42/comments?*`, (route) =>
    route.fulfill({
      json: state(
        "rejected",
        "This account is not approved for the pilot yet.",
      ),
    }),
  );
  await page.goto("/#track/42");
  await expect(page.locator("#tracking-status")).toHaveText("Not accepted");
  await expect(page.locator("#tracking-detail")).toContainText("not approved");
  await expect(page.locator("#tracking-video video")).toHaveCount(0);
});

test("foreign issues and rate limiting show actionable errors", async ({
  page,
}) => {
  await page.goto("/#track");
  await page
    .locator("#request-link")
    .fill("https://github.com/other/repo/issues/42");
  await page.locator("#track-request").click();
  await expect(page.locator("#track-message")).toContainText("this studio");
  await page.route(`${api}/issues/42`, (route) =>
    route.fulfill({ status: 403, json: { message: "rate limit" } }),
  );
  await page.locator("#request-link").fill("42");
  await page.locator("#track-request").click();
  await expect(page.locator("#track-message")).toContainText(
    "public request limit",
  );
  await expect(page.locator("#track-request")).toBeEnabled();
});

test("mobile navigation and workspace do not overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("link", { name: "Public gallery", exact: true }).click();
  await expect(page.locator("#view-gallery")).toBeVisible();
  await expect(page.locator("#view-create")).toBeHidden();
});
