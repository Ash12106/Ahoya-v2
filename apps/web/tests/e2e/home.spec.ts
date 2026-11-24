import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("home page exposes account setup and a strict CSP", async ({ page }) => {
  const response = await page.goto("/");

  expect(response?.status()).toBe(200);
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your place starts with a profile." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeDisabled();
  await expect(page.getByLabel("Account setup status")).toContainText("Google sign-in");
  const logo = page.locator('img[src="/ahoya-logo.png"]');
  await expect(logo).toBeVisible();
  await expect
    .poll(() => logo.evaluate((image) => (image as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0);

  const headers = await response?.allHeaders();
  expect(headers?.["content-security-policy"]).toContain("'strict-dynamic'");
  expect(headers?.["x-content-type-options"]).toBe("nosniff");
  expect(headers?.["x-request-id"]).toBeTruthy();
});

test("home page remains usable at 320 CSS pixels and has no axe violations", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 780 });
  await page.goto("/");

  await expect(page.getByRole("main")).toBeVisible();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(320);

  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(accessibility.violations).toEqual([]);
});

test("health endpoint reports process liveness", async ({ request }) => {
  const response = await request.get("/health");

  expect(response.status()).toBe(200);
  await expect(response).toBeOK();
  expect(await response.json()).toEqual({ status: "ok" });
});

test("profile API does not expose an unauthenticated account", async ({ request }) => {
  const response = await request.get("/api/profile");

  expect(response.status()).toBe(401);
  expect(await response.json()).toMatchObject({ code: "UNAUTHENTICATED" });
});
