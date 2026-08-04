import { test, expect } from "../src/fixtures";
import {
  appUrl,
  assertApiSuccess,
  createContest,
  dateFromNow,
  gotoLoaded,
  reloadLoaded,
  removeContestMember,
  responseJson,
  uniqueText,
  waitForContainer,
} from "../src/helpers";

test.describe("Contest lifecycle", { tag: "@contest" }, () => {
  test(
    "admin can create a Contest through the UI",
    { tag: "@admin" },
    async ({ page, signedInAdmin, baseURLValue }) => {
      const contestName = uniqueText("contest");
      await gotoLoaded(page, baseURLValue, "/contests/manage/add/");
      await page.locator("#name").fill(contestName);

      const responsePromise = page.waitForResponse(
        (response) =>
          response.url().endsWith("/be/contests/manage/add") &&
          response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Add", exact: true }).click();
      const payload = await responseJson(await responsePromise);
      expect(payload.status).toBe("S");
      const contestId = Number(payload.data);
      await page.waitForURL(new RegExp(`/contests/${contestId}/manage/general/$`));
      await waitForContainer(page);
      await expect(page.locator("#contestName")).toHaveValue(contestName);
      await expect(
        page.locator("a.nav-link.active").filter({ hasText: "General" }),
      ).toBeVisible();
    },
  );

  test("free registration registers and unregisters immediately", async ({
    page,
    adminApi,
    signedInUser,
    baseURLValue,
  }) => {
    const contest = await createContest(adminApi, baseURLValue, {
      prefix: "free-registration",
      start: dateFromNow({ days: 2 }),
      end: dateFromNow({ days: 3 }),
      regMode: 1,
      regEnd: dateFromNow({ days: 1 }),
    });

    await gotoLoaded(page, baseURLValue, `/contests/${contest.contestId}/reg/`);
    await expect(page.getByText("Status: Not Registered", { exact: true })).toBeVisible();
    let responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/be/contests/${contest.contestId}/reg`) &&
        response.request().method() === "POST",
    );
    await page.locator("button.reg").click();
    expect((await responseJson(await responsePromise)).status).toBe("S");

    await reloadLoaded(page);
    await expect(page.getByText("Status: Registered", { exact: true })).toBeVisible();
    responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/be/contests/${contest.contestId}/reg`) &&
        response.request().method() === "POST",
    );
    await page.locator("button.unreg").click();
    expect((await responseJson(await responsePromise)).status).toBe("S");

    await reloadLoaded(page);
    await expect(page.getByText("Status: Not Registered", { exact: true })).toBeVisible();
  });

  test("Contest list classifies upcoming, active and recent entries", async ({
    page,
    adminApi,
    baseURLValue,
  }) => {
    const upcoming = await createContest(adminApi, baseURLValue, {
      prefix: "upcoming",
      start: dateFromNow({ days: 2 }),
      end: dateFromNow({ days: 3 }),
    });
    const active = await createContest(adminApi, baseURLValue, {
      prefix: "active",
      start: dateFromNow({ hours: -1 }),
      end: dateFromNow({ hours: 2 }),
    });
    const recent = await createContest(adminApi, baseURLValue, {
      prefix: "recent",
      start: dateFromNow({ hours: -2 }),
      end: dateFromNow({ hours: -1 }),
      publicScoreboard: false,
    });

    await gotoLoaded(page, baseURLValue, "/contests/");
    const upcomingTable = page
      .getByRole("heading", { name: "Upcoming Contests" })
      .locator("xpath=following-sibling::table[1]");
    const activeTable = page
      .getByRole("heading", { name: "Active Contests" })
      .locator("xpath=following-sibling::table[1]");
    const recentTable = page
      .getByRole("heading", { name: "Recent Contests" })
      .locator("xpath=following-sibling::table[1]");

    await expect(
      upcomingTable.getByRole("link", { name: upcoming.name, exact: true }),
    ).toBeVisible();
    await expect(
      activeTable.getByRole("link", { name: active.name, exact: true }),
    ).toBeVisible();
    const recentRow = recentTable.locator("tr").filter({ hasText: recent.name });
    await expect(recentRow).toHaveCount(1);
    await expect(recentRow).toContainText("No");
  });

  test("private scoreboard hides guests but shows the member", async ({
    page,
    adminApi,
    e2eUser,
    baseURLValue,
    newUserSession,
  }) => {
    const contest = await createContest(adminApi, baseURLValue, {
      prefix: "private-scoreboard",
      start: dateFromNow({ hours: -1 }),
      end: dateFromNow({ hours: 2 }),
      regMode: 1,
      regEnd: dateFromNow({ hours: 1 }),
      publicScoreboard: false,
    });
    const {
      context: userContext,
      page: userPage,
      accountId,
    } = await newUserSession(e2eUser);
    let memberAdded = false;

    try {
      const registered = await userContext.request.post(
        appUrl(baseURLValue, `/be/contests/${contest.contestId}/reg`),
        { form: { reqtype: "reg" } },
      );
      await assertApiSuccess(registered, "register private scoreboard member");
      memberAdded = true;

      const guestResponse = page.waitForResponse(
        (response) =>
          response.url().endsWith(`/be/contests/${contest.contestId}/scoreboard`) &&
          response.request().method() === "POST",
      );
      await gotoLoaded(page, baseURLValue, `/contests/${contest.contestId}/scoreboard/`);
      expect((await responseJson(await guestResponse)).status).toBe("Eacces");
      await expect(page.locator("#scoreboard")).toContainText("No Scoreboard");

      const memberResponse = userPage.waitForResponse(
        (response) =>
          response.url().endsWith(`/be/contests/${contest.contestId}/scoreboard`) &&
          response.request().method() === "POST",
      );
      await gotoLoaded(
        userPage,
        baseURLValue,
        `/contests/${contest.contestId}/scoreboard/`,
      );
      expect((await responseJson(await memberResponse)).status).toBe("S");
      await expect(
        userPage.locator("#scoreboard").getByText(e2eUser.name, { exact: true }),
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

  test(
    "user can cancel a pending Contest registration",
    { tag: "@admin" },
    async ({ page, newUserSession, signedInAdmin, e2eUser, baseURLValue, context }) => {
      const contest = await createContest(context.request, baseURLValue, {
        prefix: "approval-contest",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
        regMode: 2,
        regEnd: dateFromNow({ days: 1 }),
      });
      await gotoLoaded(page, baseURLValue, `/contests/${contest.contestId}/manage/general/`);
      await expect(page.locator("#contestName")).toHaveValue(contest.name);
      await expect(page.locator("#regMode")).toHaveValue("2");

      const { context: userContext, page: userPage } = await newUserSession(e2eUser);
      try {
        await registerForContest(userPage, baseURLValue, contest.contestId);
        const responsePromise = userPage.waitForResponse(
          (response) =>
            response.url().endsWith(`/be/contests/${contest.contestId}/reg`) &&
            response.request().method() === "POST",
        );
        await userPage.locator("button.cancel-register").click();
        expect((await responseJson(await responsePromise)).status).toBe("S");
        await reloadLoaded(userPage);
        await expect(
          userPage.getByText("Status: Not Registered", { exact: true }),
        ).toBeVisible();
      } finally {
          }
    },
  );

  test(
    "admin can reject and then reapprove a registration",
    { tag: "@admin" },
    async ({ page, context, newUserSession, signedInAdmin, e2eUser, baseURLValue }) => {
      const contest = await createContest(context.request, baseURLValue, {
        prefix: "approval-contest",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
        regMode: 2,
        regEnd: dateFromNow({ days: 1 }),
      });
      const { context: userContext, page: userPage } = await newUserSession(e2eUser);
      let registered = false;

      try {
        await registerForContest(userPage, baseURLValue, contest.contestId);
        await gotoLoaded(page, baseURLValue, `/contests/${contest.contestId}/manage/reg/`);
        const requestRow = page.locator("tbody tr").filter({ hasText: e2eUser.name });
        await expect(requestRow).toHaveCount(1);
        let responsePromise = page.waitForResponse(
          (response) =>
            response.url().endsWith(
              `/be/contests/${contest.contestId}/manage/reg`,
            ) && response.request().method() === "POST",
        );
        await requestRow.locator("button.reject").click();
        expect((await responseJson(await responsePromise)).status).toBe("S");

        await reloadLoaded(userPage);
        await expect(
          userPage.getByText("Status: Rejected", { exact: true }),
        ).toBeVisible();

        await reloadLoaded(page);
        const rejectedRow = page.locator("tbody tr").filter({ hasText: e2eUser.name });
        await expect(rejectedRow).toHaveCount(1);
        page.once("dialog", (dialog) => dialog.accept());
        responsePromise = page.waitForResponse(
          (response) =>
            response.url().endsWith(
              `/be/contests/${contest.contestId}/manage/reg`,
            ) && response.request().method() === "POST",
        );
        await rejectedRow.locator("button.re-approve").click();
        expect((await responseJson(await responsePromise)).status).toBe("S");
        registered = true;

        await reloadLoaded(userPage);
        await expect(
          userPage.getByText("Status: Registered", { exact: true }),
        ).toBeVisible();
      } finally {
        if (registered) {
          const unregistered = await userContext.request.post(
            appUrl(baseURLValue, `/be/contests/${contest.contestId}/reg`),
            { form: { reqtype: "unreg" } },
          );
          await assertApiSuccess(unregistered, "unregister E2E Contest user");
        }
          }
    },
  );

  test(
    "guest can render a saved Contest description on direct load",
    { tag: "@admin" },
    async ({ page, adminApi, baseURLValue }) => {

      const contest = await createContest(adminApi, baseURLValue, {
        prefix: "guest-description",
        start: dateFromNow({ days: 2 }),
        end: dateFromNow({ days: 3 }),
      });
      const heading = uniqueText("guest-contest-heading");
      const response = await adminApi.post(
        appUrl(baseURLValue, `/be/contests/${contest.contestId}/manage/desc`),
        {
          form: {
            reqtype: "update",
            desc_type: "before",
            desc: `# ${heading}`,
          },
        },
      );
      await assertApiSuccess(response, "save Contest description");

      await page.route(
        "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
        async (route) => {
          await new Promise((resolve) => setTimeout(resolve, 1_000));
          await route.continue();
        },
      );
      await gotoLoaded(page, baseURLValue, `/contests/${contest.contestId}/info/`);
      await expect(page.locator("#desc h1")).toHaveText(heading);
    },
  );
});

async function registerForContest(
  page: Parameters<typeof gotoLoaded>[0],
  baseURL: string,
  contestId: number,
): Promise<void> {
  await gotoLoaded(page, baseURL, `/contests/${contestId}/reg/`);
  await expect(page.getByText("Status: Not Registered", { exact: true })).toBeVisible();
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/be/contests/${contestId}/reg`) &&
      response.request().method() === "POST",
  );
  await page.locator("button.reg").click();
  expect((await responseJson(await responsePromise)).status).toBe("S");
  await reloadLoaded(page);
  await expect(
    page.getByText("Status: Waiting Approval", { exact: true }),
  ).toBeVisible();
}
