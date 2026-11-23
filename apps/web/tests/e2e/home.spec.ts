import { expect, test } from "@playwright/test";

test("home page exposes the foundation status with a strict CSP", async ({ page }) => {
  const response = await page.goto("/");

  expect(response?.status()).toBe(200);
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading", { name: "A new foundation." })).toBeVisible();
  await expect(page.getByLabel("Build status")).toContainText("Foundation in progress");

  const headers = await response?.allHeaders();
  expect(headers?.["content-security-policy"]).toContain("'strict-dynamic'");
  expect(headers?.["x-content-type-options"]).toBe("nosniff");
  expect(headers?.["x-request-id"]).toBeTruthy();
});

test("health endpoint reports process liveness", async ({ request }) => {
  const response = await request.get("/health");

  expect(response.status()).toBe(200);
  await expect(response).toBeOK();
  expect(await response.json()).toEqual({ status: "ok" });
});
