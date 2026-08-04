import { test, expect } from "../src/fixtures";
import {
  appUrl,
  assertApiSuccess,
  createContest,
  dateFromNow,
  gotoLoaded,
  removeContestMember,
  responseJson,
  uniqueText,
  waitForContainer,
} from "../src/helpers";

async function waitForDelayedReload(page: Parameters<typeof gotoLoaded>[0]): Promise<void> {
  await page.waitForTimeout(1_150);
  await waitForContainer(page);
  const dialog = page.locator("#indexNotifyDialog");
  if (await dialog.isVisible()) {
    await dialog.locator(".btn-close").click();
    await expect(dialog).toBeHidden();
  }
}

test.describe(
  "Contest management",
  { tag: ["@contest", "@admin"] },
  () => {
    test("description preview is sanitized and persisted", async ({
      page,
      context,
      signedInAdmin,
      baseURLValue,
    }) => {
      const contest = await createContest(context.request, baseURLValue, {
        prefix: "markdown-description",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
      });
      const heading = uniqueText("contest-heading");
      const body = uniqueText("contest-body");
      const markdown =
        `# ${heading}\n\n**${body}**\n\n` +
        '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" ' +
        'onerror="window.__e2eUnsafe = true">';

      await gotoLoaded(
        page,
        baseURLValue,
        `/contests/${contest.contestId}/manage/desc/`,
      );
      await page.locator("#contestDesc").fill(markdown);
      await page.getByRole("button", { name: "Preview", exact: true }).click();
      const preview = page.locator("#descPreviewDialog");
      await expect(preview).toBeVisible();
      await expect(preview.locator("h1")).toHaveText(heading);
      await expect(preview.locator("strong")).toHaveText(body);
      await expect(preview.locator("script")).toHaveCount(0);
      expect(await preview.locator("img").getAttribute("onerror")).toBeNull();
      await preview.getByRole("button", { name: "Close", exact: true }).click();
      await expect(preview).toBeHidden();

      const savedMarkdown = `# ${heading}\n\n**${body}**`;
      await page.locator("#contestDesc").fill(savedMarkdown);
      const responsePromise = page.waitForResponse(
        (response) =>
          response
            .url()
            .endsWith(`/be/contests/${contest.contestId}/manage/desc`) &&
          response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Update", exact: true }).click();
      expect((await responseJson(await responsePromise)).status).toBe("S");
      await expect(page.locator("#indexNotifyDialog .modal-body")).toHaveText(
        "Update Successfully",
      );

      await gotoLoaded(
        page,
        baseURLValue,
        `/contests/${contest.contestId}/manage/desc/`,
      );
      await expect(page.locator("#descType")).toHaveValue("before");
      await expect(page.locator("#contestDesc")).toHaveValue(savedMarkdown);
    });

    test("admin can grant and revoke member and admin roles", async ({
      page,
      context,
      newUserSession,
      signedInAdmin,
      e2eUser,
      baseURLValue,
    }) => {
      test.info().annotations.push({
        type: "allow-browser-error",
        description: "marked is not defined",
      });
      const contest = await createContest(context.request, baseURLValue, {
        prefix: "role-management",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
      });
      const {
        context: userContext,
        page: userPage,
        accountId,
      } = await newUserSession(e2eUser);
      let currentRole: string | undefined;

      try {

        await gotoLoaded(
          page,
          baseURLValue,
          `/contests/${contest.contestId}/manage/acct/`,
        );
        await page.locator("#acctIdNormal").fill(String(accountId));
        let responsePromise = page.waitForResponse(
          (response) =>
            response
              .url()
              .endsWith(`/be/contests/${contest.contestId}/manage/acct`) &&
            response.request().method() === "POST",
        );
        await page.locator("#addAcctNormal").click();
        expect((await responseJson(await responsePromise)).status).toBe("S");
        currentRole = "normal";
        await waitForDelayedReload(page);
        let roleRow = page.locator("tbody tr").filter({ hasText: e2eUser.name });
        await expect(roleRow).toHaveCount(1);

        await gotoLoaded(
          userPage,
          baseURLValue,
          `/contests/${contest.contestId}/info/`,
        );
        await expect(
          userPage.getByRole("heading", { name: "Invited", exact: true }).last(),
        ).toBeVisible();
        await gotoLoaded(
          userPage,
          baseURLValue,
          `/contests/${contest.contestId}/manage/general/`,
        );
        await expect(userPage.locator("#index-cont")).toContainText("Permission denied");

        responsePromise = page.waitForResponse(
          (response) =>
            response
              .url()
              .endsWith(`/be/contests/${contest.contestId}/manage/acct`) &&
            response.request().method() === "POST",
        );
        await roleRow.locator("button.remove.normal").click();
        expect((await responseJson(await responsePromise)).status).toBe("S");
        currentRole = undefined;
        await waitForDelayedReload(page);

        await page.locator("#acctIdAdmin").fill(String(accountId));
        responsePromise = page.waitForResponse(
          (response) =>
            response
              .url()
              .endsWith(`/be/contests/${contest.contestId}/manage/acct`) &&
            response.request().method() === "POST",
        );
        await page.locator("#addAcctAdmin").click();
        expect((await responseJson(await responsePromise)).status).toBe("S");
        currentRole = "admin";
        await waitForDelayedReload(page);

        await gotoLoaded(
          userPage,
          baseURLValue,
          `/contests/${contest.contestId}/manage/general/`,
        );
        await expect(userPage.locator("#contestName")).toHaveValue(contest.name);

        roleRow = page.locator("tbody tr").filter({ hasText: e2eUser.name });
        await expect(roleRow).toHaveCount(1);
        responsePromise = page.waitForResponse(
          (response) =>
            response
              .url()
              .endsWith(`/be/contests/${contest.contestId}/manage/acct`) &&
            response.request().method() === "POST",
        );
        await roleRow.locator("button.remove.admin").click();
        expect((await responseJson(await responsePromise)).status).toBe("S");
        currentRole = undefined;

        await gotoLoaded(
          userPage,
          baseURLValue,
          `/contests/${contest.contestId}/info/`,
        );
        await expect(userPage.getByText("Not Invited", { exact: true })).toBeVisible();
      } finally {
        if (currentRole) {
          await removeContestMember(
            context.request,
            baseURLValue,
            contest.contestId,
            accountId,
            currentRole,
          );
        }
      }
    });

    test("admin can add, configure and remove a Contest problem", async ({
      page,
      context,
      signedInAdmin,
      baseURLValue,
    }) => {
      const contest = await createContest(context.request, baseURLValue, {
        prefix: "problem-management",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
      });
      const problemName = uniqueText("contest-problem");
      const createdProblem = await context.request.post(
        appUrl(baseURLValue, "/be/manage/pro/add"),
        {
          form: {
            reqtype: "addpro",
            name: problemName,
            status: "0",
            mode: "manual",
            pack_token: "",
          },
        },
      );
      const problemId = Number(
        (await assertApiSuccess(createdProblem, "create online E2E problem")).data,
      );
      let problemAdded = false;

      try {
        await gotoLoaded(
          page,
          baseURLValue,
          `/contests/${contest.contestId}/manage/pro/`,
        );
        await page.locator("#proId").fill(String(problemId));
        let responsePromise = page.waitForResponse(
          (response) =>
            response
              .url()
              .endsWith(`/be/contests/${contest.contestId}/manage/pro`) &&
            response.request().method() === "POST",
        );
        await page.locator("#addPro").click();
        expect((await responseJson(await responsePromise)).status).toBe("S");
        problemAdded = true;
        await waitForDelayedReload(page);

        let row = page.locator("tbody tr").filter({
          has: page.locator(`a[href*="/pro/${problemId}/"]`),
        });
        await expect(row).toHaveCount(1);
        responsePromise = page.waitForResponse(
          (response) =>
            response
              .url()
              .endsWith(`/be/contests/${contest.contestId}/manage/pro`) &&
            response.request().method() === "POST",
        );
        await row.locator(".score-type-select").selectOption({ label: "IOI2013" });
        expect((await responseJson(await responsePromise)).status).toBe("S");
        await waitForDelayedReload(page);

        row = page.locator("tbody tr").filter({
          has: page.locator(`a[href*="/pro/${problemId}/"]`),
        });
        await expect(row.locator(".score-type-select")).toHaveValue("0");
        responsePromise = page.waitForResponse(
          (response) =>
            response
              .url()
              .endsWith(`/be/contests/${contest.contestId}/manage/pro`) &&
            response.request().method() === "POST",
        );
        await row.locator(".challenge-style-select").selectOption({ label: "Total Only" });
        expect((await responseJson(await responsePromise)).status).toBe("S");
        await waitForDelayedReload(page);

        await gotoLoaded(
          page,
          baseURLValue,
          `/contests/${contest.contestId}/proset/`,
        );
        await expect(
          page.locator("#prolist tbody tr").filter({
            has: page.locator(`a[href*="/pro/${problemId}/"]`),
          }),
        ).toHaveCount(1);

        await gotoLoaded(
          page,
          baseURLValue,
          `/contests/${contest.contestId}/manage/pro/`,
        );
        row = page.locator("tbody tr").filter({
          has: page.locator(`a[href*="/pro/${problemId}/"]`),
        });
        await expect(row.locator(".challenge-style-select")).toHaveValue("4");
        responsePromise = page.waitForResponse(
          (response) =>
            response
              .url()
              .endsWith(`/be/contests/${contest.contestId}/manage/pro`) &&
            response.request().method() === "POST",
        );
        await row.locator("button.remove").click();
        expect((await responseJson(await responsePromise)).status).toBe("S");
        problemAdded = false;
        await waitForDelayedReload(page);
        await expect(
          page.locator("tbody tr").filter({
            has: page.locator(`a[href*="/pro/${problemId}/"]`),
          }),
        ).toHaveCount(0);
      } finally {
        if (problemAdded) {
          const removed = await context.request.post(
            appUrl(baseURLValue, `/be/contests/${contest.contestId}/manage/pro`),
            { form: { reqtype: "remove", pro_id: String(problemId) } },
          );
          await assertApiSuccess(removed, "remove E2E Contest problem");
        }
      }
    });
  },
);
