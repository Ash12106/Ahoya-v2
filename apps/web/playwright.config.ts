import { defineConfig } from "@playwright/test";

const port = Number(process.env.E2E_PORT ?? "3000");
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error("E2E_PORT must be a valid TCP port");
}
const baseURL = `http://127.0.0.1:${port}`;
const originToken = "e2e-origin-token-" + "x".repeat(32);

export default defineConfig({
  testDir: "./tests/e2e",
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    extraHTTPHeaders: { "x-ahoya-origin-token": originToken },
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run start",
    url: `${baseURL}/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    env: {
      CLOUDFLARE_ORIGIN_TOKEN: originToken,
      HOSTNAME: "127.0.0.1",
      PORT: String(port),
    },
  },
});
