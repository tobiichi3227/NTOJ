import { APIRequestContext } from "@playwright/test";
import { test, expect } from "../src/fixtures";
import {
  appUrl,
  assertApiSuccess,
  dismissNotification,
  gotoLoaded,
  responseJson,
  uniqueText,
  waitForContainer,
} from "../src/helpers";

async function removeProClass(
  api: APIRequestContext,
  baseURL: string,
  proClassId: number,
): Promise<void> {
  const response = await api.post(appUrl(baseURL, "/be/manage/proclass/update"), {
    form: { reqtype: "remove", proclass_id: String(proClassId) },
  });
  await assertApiSuccess(response, `remove problem class ${proClassId}`);
}

async function updateAccountIp(
  api: APIRequestContext,
  baseURL: string,
  accountId: number,
  specificIp: string,
): Promise<void> {
  const response = await api.post(appUrl(baseURL, "/be/manage/acct/update"), {
    form: {
      reqtype: "update",
      acct_id: String(accountId),
      acct_type: "3",
      specific_ip: specificIp,
    },
  });
  await assertApiSuccess(response, `update account ${accountId}`);
}


test.describe("administrator observability workflows", { tag: "@admin" }, () => {
  test.describe.configure({ timeout: 60_000 });
  test("admin manages an official problem class through its full lifecycle", async ({
    page,
    context,
    signedInAdmin,
    baseURLValue,
  }) => {
    const originalName = uniqueText("proclass");
    const updatedName = `${originalName}-hidden`;
    const description = `# ${originalName}\n\nMaintained by Playwright.`;
    let proClassId: number | undefined;

    try {
      await gotoLoaded(page, baseURLValue, "/manage/proclass/add/");
      await page.locator("#name").fill(originalName);
      await page.locator("#type").selectOption("0");
      await page.locator("#list").fill("1");
      await page.locator("#desc").fill(description);

      const addResponse = page.waitForResponse(
        (response) =>
          response.url().endsWith("/be/manage/proclass/add") &&
          response.request().method() === "POST",
      );
      await page.locator("#add").click();
      const addPayload = await responseJson(await addResponse);
      expect(addPayload.status).toBe("S");
      proClassId = Number(addPayload.data);
      expect(Number.isSafeInteger(proClassId) && proClassId > 0).toBeTruthy();
      await page.waitForURL(
        new RegExp(`/manage/proclass/update/\\?proclassid=${proClassId}$`),
      );
      await waitForContainer(page);
      await expect(page.locator("#name")).toHaveValue(originalName);
      await expect(page.locator("#list")).toHaveValue("1");
      await expect(page.locator("#desc")).toHaveValue(description);
      await dismissNotification(page);

      await page.locator("#name").fill(updatedName);
      await page.locator("#type").selectOption("1");
      const updateResponse = page.waitForResponse(
        (response) =>
          response.url().endsWith("/be/manage/proclass/update") &&
          response.request().method() === "POST",
      );
      await page.locator("#update").click();
      expect((await responseJson(await updateResponse)).status).toBe("S");

      await gotoLoaded(
        page,
        baseURLValue,
        `/manage/proclass/update/?proclassid=${proClassId}`,
      );
      await expect(page.locator("#name")).toHaveValue(updatedName);
      await expect(page.locator("#type")).toHaveValue("1");
      await expect(page.locator("#desc")).toHaveValue(description);

      await gotoLoaded(page, baseURLValue, "/manage/proclass/");
      const row = page.locator("tbody tr").filter({ hasText: updatedName });
      await expect(row).toHaveCount(1);
      await expect(row.locator("td").nth(1)).toHaveText("Hidden");
      await row.locator("a[href*='/manage/proclass/update/']").click();
      await page.waitForURL(
        new RegExp(`/manage/proclass/update/\\?proclassid=${proClassId}$`),
      );
      await waitForContainer(page);

      page.once("dialog", (dialog) => dialog.accept());
      const removeResponse = page.waitForResponse(
        (response) =>
          response.url().endsWith("/be/manage/proclass/update") &&
          response.request().method() === "POST",
      );
      await page.locator("#remove").click();
      expect((await responseJson(await removeResponse)).status).toBe("S");
      await page.waitForURL(appUrl(baseURLValue, "/manage/proclass/"));
      await waitForContainer(page);
      await expect(page.locator("tbody tr").filter({ hasText: updatedName })).toHaveCount(0);
      proClassId = undefined;
    } finally {
      if (proClassId !== undefined) {
        await removeProClass(context.request, baseURLValue, proClassId);
      }
    }
  });

  test("account validation and updates are visible in the global audit log", async ({
    page,
    context,
    newUserSession,
    signedInAdmin,
    e2eUser,
    baseURLValue,
  }) => {
    const { accountId } = await newUserSession(e2eUser);

    try {
      await gotoLoaded(
        page,
        baseURLValue,
        `/manage/acct/update/?acctid=${accountId}`,
      );
      await expect(page.locator("#form h3")).toContainText(e2eUser.name);
      await expect(page.locator("#type")).toHaveValue("3");

      await page.locator("#ip").fill("999.1.1.1");
      await page.locator("button.submit").click();
      await expect(page.locator("#indexNotifyDialog .modal-body")).toHaveText(
        "Specific IP format error, please input correct IP address.",
      );
      await dismissNotification(page);

      const invalidResponse = await context.request.post(
        appUrl(baseURLValue, "/be/manage/acct/update"),
        {
          form: {
            reqtype: "update",
            acct_id: String(accountId),
            acct_type: "3",
            specific_ip: "999.1.1.1",
          },
        },
      );
      const invalidPayload = await responseJson(invalidResponse);
      expect(invalidPayload.status).toBe("Einval");

      await page.locator("#ip").fill("127.0.0.1");
      const updateResponse = page.waitForResponse(
        (response) =>
          response.url().endsWith("/be/manage/acct/update") &&
          response.request().method() === "POST",
      );
      await page.locator("button.submit").click();
      expect((await responseJson(await updateResponse)).status).toBe("S");

      await gotoLoaded(
        page,
        baseURLValue,
        `/manage/acct/update/?acctid=${accountId}`,
      );
      await expect(page.locator("#ip")).toHaveValue("127.0.0.1");

      await gotoLoaded(page, baseURLValue, "/log/?logtype=manage.acct.update");
      await expect(page.locator("#logtype_list")).toHaveValue("manage.acct.update");
      const logRow = page.locator("tbody tr").filter({ hasText: e2eUser.name }).first();
      await expect(logRow).toBeVisible();
      await expect(logRow).toContainText(String(accountId));
      await logRow.locator("td.id a").click();
      await page.waitForURL(/\/log\/\d+\/$/);
      await waitForContainer(page);
      await expect(page.locator("#index-cont")).toContainText("manage.acct.update");
      await expect(page.locator("#index-cont")).toContainText(e2eUser.name);
      await expect(page.locator("#index-cont")).toContainText(String(accountId));
      await expect(page.locator("#index-cont")).toContainText("Operator IP");
      await expect(page.locator("#index-cont")).toContainText("Params");
    } finally {
      await updateAccountIp(context.request, baseURLValue, accountId, "");
    }
  });

  test("system information reports dependencies and completes database maintenance", async ({
    page,
    signedInAdmin,
    baseURLValue,
  }) => {
    await gotoLoaded(page, baseURLValue, "/manage/info/");
    for (const heading of [
      "Database Information",
      "Redis Information",
      "System Configuration",
      "Python Information",
      "Operating System Information",
      "Disk Usage",
      "System Resources",
    ]) {
      await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    }
    await expect(page.locator("#index-cont")).toContainText("PostgreSQL Version");
    await expect(page.locator("#index-cont")).toContainText("Package Dependencies");
    await expect(page.locator("#vacuum-btn")).toBeEnabled();

    page.once("dialog", (dialog) => dialog.accept());
    const vacuumResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/be/manage/info") &&
        response.request().method() === "POST",
    );
    await page.locator("#vacuum-btn").click();
    expect((await responseJson(await vacuumResponse)).status).toBe("S");
    await expect(page.locator("#indexNotifyDialog .modal-body")).toHaveText(
      "Database VACUUM completed",
    );
    await expect(page.locator("#vacuum-btn")).toBeEnabled();
    await expect(page.locator("#vacuum-btn")).toHaveText("Run VACUUM");
  });
});
