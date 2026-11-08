import { defineConfig } from "@playwright/test";
import { existsSync, readdirSync } from "fs";

// Use a locally installed Chromium when available (offline environments).
function chromium(): string | undefined {
  if (process.env.CHROMIUM_EXECUTABLE_PATH) return process.env.CHROMIUM_EXECUTABLE_PATH;
  const root = "/opt/pw-browsers";
  if (!existsSync(root)) return undefined;
  const dir = readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort().pop();
  if (!dir) return undefined;
  return ["chrome-linux64", "chrome-linux"].map((d) => `${root}/${dir}/${d}/chrome`).find((p) => existsSync(p));
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    launchOptions: { executablePath: chromium() },
    trace: "retain-on-failure",
  },
});
