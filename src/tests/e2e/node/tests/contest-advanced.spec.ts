import { test, expect } from "../src/fixtures";
import {
  addContestMember,
  appUrl,
  assertApiSuccess,
  createContest,
  dateFromNow,
  gotoLoaded,
  reloadLoaded,
  removeContestMember,
  responseJson,
} from "../src/helpers";

async function submitGeneralSettings(
  page: Parameters<typeof gotoLoaded>[0],
  contestId: number,
): Promise<void> {
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/be/contests/${contestId}/manage/general`) &&
      response.request().method() === "POST",
  );
  await page.locator("button.submit").click();
  expect((await responseJson(await responsePromise)).status).toBe("S");
  await expect(page.locator("#indexNotifyDialog .modal-body")).toHaveText(
    "Update Successfully",
  );
}

test.describe(
  "Contest advanced workflows",
  { tag: ["@contest", "@admin"] },
  () => {
    test("general settings switch to ACM defaults and persist", async ({
      page,
      context,
      signedInAdmin,
      baseURLValue,
    }) => {
      const contest = await createContest(context.request, baseURLValue, {
        prefix: "general-settings",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
      });

      await gotoLoaded(
        page,
        baseURLValue,
        `/contests/${contest.contestId}/manage/general/`,
      );
      await expect(page.locator("#contestMode")).toHaveValue("0");
      await expect(page.locator("#submitCdTime")).toHaveValue("30");
      await expect(page.locator("#penaltyValueContainer")).toBeHidden();

      await page.locator("#contestMode").selectOption({ label: "ACM" });
      await expect(page.locator("#submitCdTime")).toHaveValue("1");
      await expect(page.locator("#penaltyValueContainer")).toBeVisible();
      await page.locator("#penaltyValue").fill("25");
      await page.locator("#freezeScoreboardPeriod").fill("15");
      await page.locator("#publicScoreboard").uncheck();
      await page.locator("#enableSystemTest").check();
      await submitGeneralSettings(page, contest.contestId);

      await gotoLoaded(
        page,
        baseURLValue,
        `/contests/${contest.contestId}/manage/general/`,
      );
      await expect(page.locator("#contestMode")).toHaveValue("1");
      await expect(page.locator("#submitCdTime")).toHaveValue("1");
      await expect(page.locator("#penaltyValue")).toHaveValue("25");
      await expect(page.locator("#freezeScoreboardPeriod")).toHaveValue("15");
      await expect(page.locator("#publicScoreboard")).not.toBeChecked();
      await expect(page.locator("#enableSystemTest")).toBeChecked();
    });

    test("changing approval registration to free approves pending users", async ({
      page,
      context,
      signedInAdmin,
      e2eUser,
      newUserSession,
      baseURLValue,
    }) => {
      const contest = await createContest(context.request, baseURLValue, {
        prefix: "approval-to-free",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
        regMode: 2,
        regEnd: dateFromNow({ days: 1 }),
      });
      const { context: userContext, page: userPage } =
        await newUserSession(e2eUser);
      let approved = false;

      const registration = await userContext.request.post(
        appUrl(baseURLValue, `/be/contests/${contest.contestId}/reg`),
        { form: { reqtype: "reg" } },
      );
      await assertApiSuccess(registration, "request approval before mode transition");

      try {
        await gotoLoaded(
          userPage,
          baseURLValue,
          `/contests/${contest.contestId}/reg/`,
        );
        await expect(
          userPage.getByText("Status: Waiting Approval", { exact: true }),
        ).toBeVisible();

        await gotoLoaded(
          page,
          baseURLValue,
          `/contests/${contest.contestId}/manage/general/`,
        );
        await page.locator("#regMode").selectOption("1");
        await submitGeneralSettings(page, contest.contestId);

        await reloadLoaded(userPage);
        await expect(
          userPage.getByText("Status: Registered", { exact: true }),
        ).toBeVisible();
        approved = true;
      } finally {
        if (approved) {
          const unregister = await userContext.request.post(
            appUrl(baseURLValue, `/be/contests/${contest.contestId}/reg`),
            { form: { reqtype: "unreg" } },
          );
          await assertApiSuccess(unregister, "unregister transitioned Contest user");
        }
      }
    });

    test("invited mode exposes no registration action until member is added", async ({
      page,
      adminApi,
      signedInUser,
      baseURLValue,
    }) => {
      const contest = await createContest(adminApi, baseURLValue, {
        prefix: "invited-only",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
        regMode: 0,
      });
      await gotoLoaded(page, baseURLValue, "/info/");
      const accountId = await page.evaluate(
        () => (window as typeof window & { index: { acct_id: number } }).index.acct_id,
      );
      let memberAdded = false;

      try {
        await gotoLoaded(
          page,
          baseURLValue,
          `/contests/${contest.contestId}/reg/`,
        );
        await expect(
          page.getByText("Status: Not Invited", { exact: true }),
        ).toBeVisible();
        await expect(
          page.locator("button.reg, button.unreg, button.cancel-register"),
        ).toHaveCount(0);

        await addContestMember(
          adminApi,
          baseURLValue,
          contest.contestId,
          accountId,
        );
        memberAdded = true;
        await reloadLoaded(page);
        await expect(
          page.getByText("Status: Invited", { exact: true }),
        ).toBeVisible();
      } finally {
        if (memberAdded) {
          await removeContestMember(
            adminApi,
            baseURLValue,
            contest.contestId,
            accountId,
          );
        }
      }
    });

    test("Contest creator cannot be removed from the admin list", async ({
      page,
      context,
      signedInAdmin,
      baseURLValue,
    }) => {
      await gotoLoaded(page, baseURLValue, "/info/");
      const creatorId = await page.evaluate(
        () => (window as typeof window & { index: { acct_id: number } }).index.acct_id,
      );
      const contest = await createContest(context.request, baseURLValue, {
        prefix: "creator-protection",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
      });

      await gotoLoaded(
        page,
        baseURLValue,
        `/contests/${contest.contestId}/manage/acct/`,
      );
      const creatorRow = page.locator("tbody tr").filter({
        has: page.locator(`a[href*="/acct/${creatorId}/"]`),
      });
      await expect(creatorRow).toHaveCount(1);
      await page.locator("#acctIdAdmin").fill(String(creatorId));

      const responsePromise = page.waitForResponse(
        (response) =>
          response.url().endsWith(`/be/contests/${contest.contestId}/manage/acct`) &&
          response.request().method() === "POST",
      );
      await page.locator("#removeAcctAdmin").click();
      const payload = await responseJson(await responsePromise);
      expect(payload.status).toBe("Eacces");
      expect(payload.data).toBe("Cannot remove contest creator");
      await expect(page.locator("#indexNotifyDialog .modal-body")).toHaveText(
        "Cannot remove contest creator",
      );
      await expect(creatorRow).toHaveCount(1);
    });

    test("expired registration deadline hides the register action", async ({
      page,
      adminApi,
      signedInUser,
      baseURLValue,
    }) => {
      const contest = await createContest(adminApi, baseURLValue, {
        prefix: "registration-ended",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
        regMode: 1,
        regEnd: dateFromNow({ hours: -1 }),
      });


      await gotoLoaded(
        page,
        baseURLValue,
        `/contests/${contest.contestId}/reg/`,
      );
      await expect(
        page.getByText("Status: Not Registered", { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("heading", { name: "Registration Ended", exact: true }),
      ).toBeVisible();
      await expect(page.locator("button.reg")).toHaveCount(0);
    });

    test("management audit log exposes Contest-scoped update details", async ({
      page,
      context,
      signedInAdmin,
      baseURLValue,
    }) => {
      const contest = await createContest(context.request, baseURLValue, {
        prefix: "audit-log",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
      });

      await gotoLoaded(
        page,
        baseURLValue,
        `/contests/${contest.contestId}/manage/log/`,
      );
      await expect(
        page.locator('#logtype_list option[value="contest.manage.update.general"]'),
      ).toHaveCount(1);
      const row = page.locator("tbody tr").filter({
        hasText: `updated general settings of contest '${contest.name}'`,
      });
      await expect(row).toHaveCount(1);
      await row.locator("td.id a").click();
      await page.waitForURL(
        new RegExp(`/contests/${contest.contestId}/manage/log/\\d+/$`),
      );

      const detail = page.locator(".card-body");
      await expect(detail).toContainText("contest.manage.update.general");
      await expect(detail).toContainText(String(contest.contestId));
      await expect(detail).toContainText(contest.name);
    });
  },
);
