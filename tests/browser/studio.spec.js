import { test, expect } from "@playwright/test";
const api = "https://api.github.com/repos/sheerazautomate/HeyGen";
const asset =
  "https://github.com/sheerazautomate/HeyGen/releases/download/video-pilot-42/video.mp4";
const release = {
  id: 1,
  tag_name: "video-pilot-42",
  name: "A pro test video",
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

test("studio loads and example can be prepared", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("body")).toBeVisible();
  await expect(page.getByRole("button", { name: /Try an example/ })).toBeVisible({ timeout: 10000 });
  await page.getByRole("button", { name: /Try an example/ }).click();
  await expect(page.locator("#file-name")).toHaveText("product-launch.html", { timeout: 10000 });
  await expect(page.locator("#prepare")).toBeVisible();
});

test("gallery empty state", async ({ page }) => {
  await page.goto("/#gallery");
  await expect(page.locator("#gallery-empty")).toBeVisible({ timeout: 5000 });
  await page.route(`${api}/releases?*`, (route) =>
    route.fulfill({ json: [release] }),
  );
  await page.locator("#refresh-gallery").click();
  await expect(page.locator(".video-card")).toBeVisible({ timeout: 5000 });
});

test("tracking shows ready", async ({ page }) => {
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
});

test("mobile navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator("#view-create")).toBeVisible({ timeout: 5000 });
  const galleryLink = page.getByRole("link", { name: /gallery/i });
  await galleryLink.click();
  await expect(page.locator("#view-gallery")).toBeVisible({ timeout: 5000 });
});
