import { APIRequestContext } from "@playwright/test";
import { test, expect } from "../src/fixtures";

import {
  appUrl,
  assertApiSuccess,
  dateFromNow,
  gotoLoaded,
  responseJson,
  uniqueText,
  waitForContainer,
} from "../src/helpers";

async function removeBulletin(
  api: APIRequestContext,
  baseURL: string,
  bulletinId: number,
): Promise<void> {
  const response = await api.post(appUrl(baseURL, "/be/manage/bulletin/update"), {
    form: { reqtype: "remove", bulletin_id: String(bulletinId) },
  });
  await assertApiSuccess(response, `remove bulletin ${bulletinId}`);
}

test.describe("administrator workflows", { tag: "@admin" }, () => {
  test("admin can create and preview a bulletin", async ({
    page,
    context,
    signedInAdmin,
    baseURLValue,
  }) => {
    const title = uniqueText("bulletin");
    const content = `# ${title}\n\nCreated by Playwright.`;
    let bulletinId: number | undefined;

    try {
      await gotoLoaded(page, baseURLValue, "/manage/bulletin/add/");
      await page.waitForFunction(
        () => Boolean((window as typeof window & { marked?: unknown }).marked),
      );
      await page.locator("#title").fill(title);
      await page.locator("#color").fill("white");
      await page.locator("#content").fill(content);
      await page.locator("#preview").click();
      await expect(page.locator("#descPreviewDialog .modal-body h1")).toHaveText(title);
      await page.locator("#descPreviewDialog button").filter({ hasText: "Close" }).click();

      const responsePromise = page.waitForResponse(
        (response) =>
          response.url().endsWith("/be/manage/bulletin/add") &&
          response.request().method() === "POST",
      );
      await page.locator("#add").click();
      const payload = await responseJson(await responsePromise);
      expect(payload.status).toBe("S");
      bulletinId = Number(payload.data);

      await page.waitForURL(
        new RegExp(`/manage/bulletin/update/\\?bulletin_id=${bulletinId}$`),
      );
      await waitForContainer(page);
      await expect(page.locator("#title")).toHaveValue(title);
      await expect(page.locator("#content")).toHaveValue(content);
    } finally {
      if (bulletinId !== undefined) {
        await removeBulletin(context.request, baseURLValue, bulletinId);
      }
    }
  });

  test(
    "browser receives a new bulletin WebSocket notification",
    { tag: "@realtime" },
    async ({ page, adminApi, baseURLValue }) => {
      const title = uniqueText("bulletin-ws");
      let bulletinId: number | undefined;
      await gotoLoaded(page, baseURLValue, "/info/");
      await page.waitForFunction(
        () =>
          (window as typeof window & { index: { ws: WebSocket } }).index.ws.readyState ===
          WebSocket.OPEN,
      );
      await page.evaluate(() => {
        const appWindow = window as typeof window & {
          index: {
            register_ws_callback: (
              action: string,
              callback: (data: string) => void,
            ) => void;
          };
          __e2eBulletins?: number[];
        };
        appWindow.__e2eBulletins = [];
        appWindow.index.register_ws_callback("bulletinsub", (data) =>
          appWindow.__e2eBulletins!.push(Number(data)),
        );
      });

      try {
        const created = await adminApi.post(
          appUrl(baseURLValue, "/be/manage/bulletin/add"),
          {
            form: {
              reqtype: "add",
              title,
              content: title,
              color: "white",
              pinned: "false",
            },
          },
        );
        const payload = await assertApiSuccess(
          created,
          "create bulletin for WebSocket test",
        );
        bulletinId = Number(payload.data);
        await page.waitForFunction(
          () =>
            (window as typeof window & { __e2eBulletins?: number[] }).__e2eBulletins!
              .length > 0,
        );

        await page.evaluate(() =>
          (window as typeof window & { index: { reload: () => void } }).index.reload(),
        );
        await expect(page.getByRole("link", { name: title, exact: true })).toBeVisible();
        await waitForContainer(page);
      } finally {
        if (bulletinId !== undefined) {
          await removeBulletin(adminApi, baseURLValue, bulletinId);
        }
      }
    },
  );

  test(
    "admin can publish and then hide a board",
    { tag: "@standard" },
    async ({ page, context, newTrackedContext, signedInAdmin, baseURLValue }) => {
      const boardName = uniqueText("board");
      const hiddenName = `${boardName}-hidden`;
      const created = await context.request.post(
        appUrl(baseURLValue, "/be/manage/board/add"),
        {
          form: {
            reqtype: "add",
            name: boardName,
            status: "0",
            start: dateFromNow({ hours: -1 }).toISOString(),
            end: dateFromNow({ days: 1 }).toISOString(),
            pro_list: "1",
            acct_list: "1",
          },
        },
      );
      const createdPayload = await assertApiSuccess(created, "create E2E board");
      const boardId = Number(createdPayload.data);
      const guestContext = await newTrackedContext();
      const guestPage = await guestContext.newPage();

      try {
        await gotoLoaded(guestPage, baseURLValue, "/board/");
        await expect(
          guestPage.getByRole("link", { name: boardName, exact: true }),
        ).toBeVisible();
        await gotoLoaded(guestPage, baseURLValue, `/board/${boardId}/`);
        await expect(guestPage.locator("#board1")).toBeVisible();
        await expect(
          guestPage.getByRole("combobox").locator("option:checked"),
        ).toHaveText(boardName);

        await gotoLoaded(
          page,
          baseURLValue,
          `/manage/board/update/?boardid=${boardId}`,
        );
        await page.locator("#name").fill(hiddenName);
        await page.locator("#status").selectOption({ label: "Hidden" });

        const updateResponse = page.waitForResponse(
          (response) =>
            response.url().endsWith("/be/manage/board/update") &&
            response.request().method() === "POST",
        );
        await page.locator("#update").click();
        expect((await responseJson(await updateResponse)).status).toBe("S");
        await expect(page.locator("#indexNotifyDialog .modal-body")).toHaveText(
          "Update Successfully",
        );

        await gotoLoaded(guestPage, baseURLValue, "/board/");
        await expect(
          guestPage.getByRole("link", { name: hiddenName, exact: true }),
        ).toHaveCount(0);
        await gotoLoaded(guestPage, baseURLValue, `/board/${boardId}/`);
        await expect(guestPage.locator("#board1")).toHaveCount(0);
        await expect(guestPage.locator("#index-cont")).toContainText(
          "Permission denied",
        );
      } finally {
        const removed = await context.request.post(
          appUrl(baseURLValue, "/be/manage/board/update"),
          {
            form: { reqtype: "remove", board_id: String(boardId) },
          },
        );
        await assertApiSuccess(removed, "remove E2E board");
      }
    },
  );

  test(
    "admin can reply to a user question",
    { tag: "@standard" },
    async ({ page, newUserSession, signedInAdmin, e2eUser, baseURLValue }) => {
      const question = uniqueText("question-for-admin");
      const reply = uniqueText("admin-reply");
      const {
        context: userContext,
        page: userPage,
      } = await newUserSession(e2eUser);
      let questionAdded = false;

      try {
        const asked = await userContext.request.post(
          appUrl(baseURLValue, "/be/question"),
          { form: { reqtype: "ask", qtext: question } },
        );
        await assertApiSuccess(asked, "ask E2E question");
        questionAdded = true;

        await gotoLoaded(page, baseURLValue, "/manage/question/");
        const row = page.locator("tbody tr").filter({ hasText: e2eUser.name });
        await expect(row).toHaveCount(1);
        await row.locator("a[href*='/manage/question/reply/']").click();
        await page.waitForURL(/\/manage\/question\/reply\/\?qacct=\d+$/);
        await waitForContainer(page);

        await expect(page.getByText(question, { exact: true })).toBeVisible();
        await page.locator('textarea[id="0"]').fill(reply);
        const replyResponse = page.waitForResponse(
          (response) =>
            response.url().endsWith("/be/manage/question/reply") &&
            response.request().method() === "POST",
        );
        await page.locator('input[value="Reply"]').click();
        expect((await responseJson(await replyResponse)).status).toBe("S");
        await expect(page.locator("#indexNotifyDialog .modal-body")).toHaveText(
          "Reply Successfully",
        );

        await gotoLoaded(userPage, baseURLValue, "/question/");
        await expect(userPage.getByText(question, { exact: true })).toBeVisible();
        await expect(userPage.getByText("Reply:", { exact: true })).toBeVisible();
        await expect(userPage.locator("#form h5").filter({ hasText: reply })).toBeVisible();
      } finally {
        if (questionAdded) {
          const removed = await userContext.request.post(
            appUrl(baseURLValue, "/be/question"),
            { form: { reqtype: "rm_ques", index: "0" } },
          );
          await assertApiSuccess(removed, "remove replied E2E question");
        }
      }
    },
  );
});
