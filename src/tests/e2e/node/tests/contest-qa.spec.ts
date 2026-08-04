import {
  BrowserContext,
  Page,
} from "@playwright/test";
import { test, expect, type NewUserSession } from "../src/fixtures";
import {
  ContestIdentity,
  UserIdentity,
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

type RunningContest = {
  contest: ContestIdentity;
  userContext: BrowserContext;
  userPage: Page;
  accountId: number;
};

async function runningContestWithUser(
  adminContext: BrowserContext,
  newUserSession: NewUserSession,
  user: UserIdentity,
  baseURL: string,
): Promise<RunningContest> {
  const contest = await createContest(adminContext.request, baseURL, {
    prefix: "running-qa",
    start: dateFromNow({ hours: -1 }),
    end: dateFromNow({ hours: 2 }),
    regMode: 1,
    regEnd: dateFromNow({ hours: 1 }),
  });
  const {
    context: userContext,
    page: userPage,
    accountId,
  } = await newUserSession(user);
  const registered = await userContext.request.post(
    appUrl(baseURL, `/be/contests/${contest.contestId}/reg`),
    { form: { reqtype: "reg" } },
  );
  await assertApiSuccess(registered, "register Contest Q&A member");
  return { contest, userContext, userPage, accountId };
}

test.describe(
  "Contest Q&A and announcements",
  { tag: ["@contest", "@admin"] },
  () => {
    test("member can ask a question and receive an admin reply", async ({
      page,
      context,
      newUserSession,
      signedInAdmin,
      e2eUser,
      baseURLValue,
    }) => {
      const { contest, userContext, userPage, accountId } =
        await runningContestWithUser(
          context,
          newUserSession,
          e2eUser,
          baseURLValue,
        );
      const subject = uniqueText("contest-question");
      const content = uniqueText("contest-question-content");
      const reply = uniqueText("contest-answer");

      try {
        await gotoLoaded(
          userPage,
          baseURLValue,
          `/contests/${contest.contestId}/qa/`,
        );
        await userPage.locator("#subject").fill(subject);
        await userPage.locator("#content").fill(content);
        let responsePromise = userPage.waitForResponse(
          (response) =>
            response.url().endsWith(`/be/contests/${contest.contestId}/qa`) &&
            response.request().method() === "POST",
        );
        await userPage.locator("#ask").click();
        expect((await responseJson(await responsePromise)).status).toBe("S");
        await reloadLoaded(userPage);
        await expect(userPage.getByText(subject, { exact: true })).toBeVisible();

        await gotoLoaded(
          page,
          baseURLValue,
          `/contests/${contest.contestId}/manage/question/`,
        );
        const questionRow = page.locator("tbody tr").filter({ hasText: subject });
        await expect(questionRow).toHaveCount(1);
        const replyCell = questionRow.locator("td.reply");
        await replyCell.locator(".answer-type").selectOption("Other");
        await replyCell.locator("textarea").fill(reply);
        responsePromise = page.waitForResponse(
          (response) =>
            response
              .url()
              .endsWith(`/be/contests/${contest.contestId}/manage/question`) &&
            response.request().method() === "POST",
        );
        await replyCell.locator("button.reply").click();
        expect((await responsePromise).ok()).toBeTruthy();
        await page.waitForLoadState("domcontentloaded");

        await reloadLoaded(userPage);
        await expect(userPage.getByText(reply, { exact: true })).toBeVisible();
      } finally {
        await removeContestMember(
          context.request,
          baseURLValue,
          contest.contestId,
          accountId,
        );
      }
    });

    test(
      "announcement updates the badge and can popup over WebSocket",
      { tag: "@realtime" },
      async ({
        page,
        context,
        newUserSession,
        signedInAdmin,
        e2eUser,
        baseURLValue,
      }) => {
        const { contest, userContext, userPage, accountId } =
          await runningContestWithUser(
            context,
            newUserSession,
            e2eUser,
            baseURLValue,
          );
        test.info().annotations.push({
          type: "allow-browser-error",
          description: "marked is not defined",
        });
        const subject = uniqueText("contest-announcement");
        const content = uniqueText("contest-announcement-content");

        try {
          await gotoLoaded(
            userPage,
            baseURLValue,
            `/contests/${contest.contestId}/info/`,
          );
          await userPage.waitForFunction(
            () =>
              (window as typeof window & { index: { ws: WebSocket } }).index.ws
                .readyState === WebSocket.OPEN,
          );
          await userPage.waitForTimeout(200);

          await gotoLoaded(
            page,
            baseURLValue,
            `/contests/${contest.contestId}/manage/announce/`,
          );
          await page.locator("#form #subject").fill(subject);
          await page.locator("#form #content").fill(content);
          let responsePromise = page.waitForResponse(
            (response) =>
              response
                .url()
                .endsWith(`/be/contests/${contest.contestId}/manage/announce`) &&
              response.request().method() === "POST",
          );
          await page.locator("#add").click();
          expect((await responseJson(await responsePromise)).status).toBe("S");
          await waitForContainer(page);

          await expect(userPage.locator("#notifyRedDot")).toBeVisible();
          await expect(userPage.locator("#notifyRedDot")).toHaveText("1");

          const announceCell = page.locator("td.announce").filter({ hasText: subject });
          await expect(announceCell).toHaveCount(1);
          await page
            .locator("#indexNotifyDialog")
            .getByRole("button", { name: "Close" })
            .last()
            .click();
          await expect(page.locator("#indexNotifyDialog")).toBeHidden();
          responsePromise = page.waitForResponse(
            (response) =>
              response
                .url()
                .endsWith(`/be/contests/${contest.contestId}/manage/announce`) &&
              response.request().method() === "POST",
          );
          await announceCell.locator("button.popup").click();
          expect((await responsePromise).ok()).toBeTruthy();

          await expect(userPage.locator("#indexNotifyDialog .modal-title")).toHaveText(
            subject,
          );
          await expect(userPage.locator("#indexNotifyDialog .modal-body")).toHaveText(
            content,
          );

          await gotoLoaded(
            userPage,
            baseURLValue,
            `/contests/${contest.contestId}/qa/`,
          );
          await expect(userPage.getByText(subject, { exact: true })).toBeVisible();
          await expect(userPage.getByText(content, { exact: true })).toBeVisible();
        } finally {
          await removeContestMember(
            context.request,
            baseURLValue,
            contest.contestId,
            accountId,
          );
            }
      },
    );
  },
);
