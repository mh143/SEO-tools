import { expect, Page, test } from "@playwright/test";

// Requires: backend (TASK_BACKEND=inline, AI_PROVIDER=mock, BILLING_MODE=dev, SSRF_DEV_ALLOW_HOSTS=127.0.0.1),
// frontend on :3000, and backend/scripts/e2e_fixtures.py (demo site :8301, fake WordPress :8302).
const DEMO = process.env.E2E_DEMO_SITE || "http://127.0.0.1:8301";
const WP = process.env.E2E_WP_SITE || "http://127.0.0.1:8302";
const PASSWORD = "e2e-password-123456";

async function signup(page: Page, email: string, org: string) {
  await page.goto("/signup");
  await page.fill("input[name=email]", email);
  await page.fill("input[name=password]", PASSWORD);
  await page.fill("input[name=org]", org);
  await page.getByTestId("signup-submit").click();
  await expect(page).toHaveURL(/\/app\/[0-9a-f-]{36}$/);
  return page.url().split("/app/")[1];
}

test("public quick audit from the landing page", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("audit-url").fill(DEMO + "/");
  await page.getByTestId("audit-submit").click();
  await expect(page).toHaveURL(/\/audit\//);
  await expect(page.getByTestId("scores")).toBeVisible();
  await expect(page.getByText("Broken internal link to a 404 page").first()).toBeVisible();
  // Expand a finding to see evidence
  await page.getByText("Broken internal link to a 404 page").first().click();
  await expect(page.getByText("target_status").first()).toBeVisible();
});

test("blocked internal URL shows an error", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("audit-url").fill("http://169.254.169.254/latest/meta-data/");
  await page.getByTestId("audit-submit").click();
  await expect(page.getByRole("alert").or(page.getByText(/not allowed/i)).first()).toBeVisible();
});

test("audit, AI fix, approval, WordPress publish, verification and rollback", async ({ page }) => {
  const orgId = await signup(page, `owner-${Date.now()}@example.com`, "E2E Agency");
  // Dev billing: upgrade to Pro (simulated) to unlock publishing
  await page.goto(`/app/${orgId}/billing`);
  await expect(page.getByTestId("dev-billing")).toBeVisible();
  await page.getByTestId("choose-pro").click();
  await expect(page.getByText("pro", { exact: true }).first()).toBeVisible();

  // Add the WordPress site and run an audit
  await page.goto(`/app/${orgId}/websites`);
  await page.fill("input[name=url]", WP + "/");
  await page.fill("input[name=name]", "Bean There WP");
  await page.getByRole("button", { name: "Add website" }).click();
  await expect(page.getByRole("heading", { name: "Bean There WP" })).toBeVisible();
  await page.getByTestId("start-crawl").click();
  await expect(page).toHaveURL(/\/crawls\//);
  await expect(page.getByTestId("scores")).toBeVisible();

  // Connect WordPress with an application password
  await page.goto(`/app/${orgId}/integrations`);
  await page.getByRole("button", { name: "Connect WordPress" }).click();
  await page.getByText("Or paste an application password").click();
  await page.getByLabel("WordPress username").fill("admin");
  await page.getByLabel("Application password").fill("abcd EFGH 1234 ijkl MNOP 5678");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("set_title")).toBeVisible();
  await expect(page.getByText(/WordPress core has no meta description field/)).toBeVisible();

  // Open the short-title finding on /about/ and generate a fix
  await page.goto(`/app/${orgId}`);
  await page.getByText("View latest audit").click();
  await page.getByRole("button", { name: /Very short title/ }).click();
  await page.getByLabel("Search").fill("/about/");
  await expect(page.getByTestId("issue-row")).toHaveCount(1);
  await page.getByRole("link", { name: "Very short title" }).first().click();
  await expect(page.getByText(/\/about\//).first()).toBeVisible();
  await expect(page.getByText("Can be published directly via wordpress")).toBeVisible();
  await page.getByTestId("generate-fix").click();
  await expect(page).toHaveURL(/\/fixes\//);
  await expect(page.getByTestId("diff")).toBeVisible();
  await expect(page.getByText(/mock AI provider/)).toBeVisible();

  // Edit, submit, approve, publish
  await page.locator("input[name=title]").fill("About Bean There Coffee Roasters");
  await page.getByTestId("save-draft").click();
  await expect(page.getByTestId("diff")).toContainText("Bean There Coffee Roasters");
  await page.getByTestId("submit-fix").click();
  await page.getByTestId("approve-fix").click();
  await page.getByTestId("publish-fix").click();
  await expect(page.getByTestId("fix-verified")).toBeVisible();
  await expect(page.getByText("<title> contains the new title")).toBeVisible();
  const history = page.getByTestId("fix-history");
  for (const s of ["drafted", "awaiting approval", "approved", "applying", "verifying", "verified"]) {
    await expect(history.getByText(s, { exact: true }).first()).toBeVisible();
  }

  // Roll back
  page.once("dialog", (d) => d.accept());
  await page.getByTestId("rollback-fix").click();
  await expect(page.getByText("rolled back", { exact: true }).first()).toBeVisible();

  // Change history lists the transitions
  await page.goto(`/app/${orgId}/changes`);
  await expect(page.getByText("Original content restored.")).toBeVisible();
});

test("another tenant cannot open the first tenant's workspace", async ({ browser }) => {
  const a = await browser.newPage();
  const orgA = await signup(a, `a-${Date.now()}@example.com`, "Tenant A");
  const b = await (await browser.newContext()).newPage();
  await signup(b, `b-${Date.now()}@example.com`, "Tenant B");
  await b.goto(`/app/${orgA}`);
  await expect(b.getByText("Workspace not found or you do not have access.")).toBeVisible();
  const status = await b.evaluate(async (id) => (await fetch(`/api/orgs/${id}/websites`)).status, orgA);
  expect(status).toBe(404);
});
