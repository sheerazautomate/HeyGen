import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: true,
  use: {
    baseURL: "http://127.0.0.1:4173",
    launchOptions: process.env.TEST_CHROMIUM_PATH
      ? {
          executablePath: process.env.TEST_CHROMIUM_PATH,
          args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        }
      : {},
  },
  webServer: {
    command:
      "python3 scripts/build_site.py && python3 -m http.server 4173 --bind 0.0.0.0 --directory build/site",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
  },
});
