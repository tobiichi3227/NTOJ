import { test, expect } from "../src/fixtures";
import {
  appUrl,
  assertApiSuccess,
  gotoLoaded,
  reloadLoaded,
  responseJson,
  uniqueText,
  waitForContainer,
} from "../src/helpers";

test.describe("authentication", { tag: "@auth" }, () => {
  test("failed login stays on the sign page", async ({ page, baseURLValue }) => {
    await gotoLoaded(page, baseURLValue, "/sign/");
    await page.locator("#signin input.mail").fill("missing-e2e-user@example.test");
    await page.locator("#signin input.pw").fill("wrong-password");

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/be/sign") && response.request().method() === "POST",
    );
    await page.locator("#signin button.submit").click();
    const payload = await responseJson(await responsePromise);

    expect(payload.status).toBe("Esign");
    await expect(page.locator("#signin div.print")).toHaveText("Login failed");
    await expect(page).toHaveURL(appUrl(baseURLValue, "/sign/"));
  });

  test("user can register and sign out through the UI", async ({
    page,
    baseURLValue,
    identity,
  }) => {
    await gotoLoaded(page, baseURLValue, "/sign/");
    await page.locator("#signin button.signup").click();
    await expect(page.locator("#warning")).toBeVisible();
    await page.locator("#warning button.confirm").click();
    await expect(page.locator("#signup")).toBeVisible();

    await page.locator("#signup input.name").fill(identity.name);
    await page.locator("#signup input.mail").fill(identity.email);
    await page.locator("#signup input.pw").fill(identity.password);
    await page.locator("#signup input.repeat").fill(identity.password);

    const signupResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/be/sign") && response.request().method() === "POST",
    );
    await page.locator("#signup button.submit").click();
    expect((await signupResponse).ok()).toBeTruthy();

    await page.waitForURL(appUrl(baseURLValue, "/info/"));
    await waitForContainer(page);
    await expect(page.locator("#index-navlist a.account")).toHaveText(identity.name);

    const signoutResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/be/sign") && response.request().method() === "POST",
    );
    await page.locator("#index-navlist li.leave a").click();
    await signoutResponse;
    await page.waitForURL(appUrl(baseURLValue, "/sign/"));
    await waitForContainer(page);
    await expect(page.locator("#signin")).toBeVisible();
  });

  test("existing user can log in through the UI", async ({
    page,
    baseURLValue,
    e2eUser,
  }) => {
    await gotoLoaded(page, baseURLValue, "/sign/");
    await page.locator("#signin input.mail").fill(e2eUser.email);
    await page.locator("#signin input.pw").fill(e2eUser.password);

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/be/sign") && response.request().method() === "POST",
    );
    await page.locator("#signin button.submit").click();
    expect((await responsePromise).ok()).toBeTruthy();

    await page.waitForURL(appUrl(baseURLValue, "/info/"));
    await waitForContainer(page);
    await expect(page.locator("#index-navlist a.account")).toHaveText(e2eUser.name);
  });

  test(
    "signout closes the authenticated browser WebSocket",
    { tag: "@realtime" },
    async ({ page, context, signedInUser, baseURLValue }) => {
      await gotoLoaded(page, baseURLValue, "/info/");
      await page.waitForFunction(
        () =>
          (window as typeof window & { index: { ws: WebSocket } }).index.ws.readyState ===
          WebSocket.OPEN,
      );
      await page.evaluate(() => {
        const appWindow = window as typeof window & {
          index: { ws: WebSocket };
          __e2eWsClosed?: boolean;
        };
        appWindow.__e2eWsClosed = false;
        appWindow.index.ws.addEventListener(
          "close",
          () => {
            appWindow.__e2eWsClosed = true;
          },
          { once: true },
        );
      });

      const response = await context.request.post(appUrl(baseURLValue, "/be/sign"), {
        form: { reqtype: "signout" },
      });
      expect((await responseJson(response)).status).toBe("S");
      await page.waitForFunction(
        () =>
          (window as typeof window & { __e2eWsClosed?: boolean }).__e2eWsClosed === true,
      );
    },
  );

  test(
    "user can remotely log out another browser session",
    { tag: "@realtime" },
    async ({ page, context, newUserSession, signedInUser, baseURLValue }) => {
      await page.waitForTimeout(1_100);
      const {
        context: secondaryContext,
        page: secondaryPage,
      } = await newUserSession(signedInUser, {
        userAgent: "NTOJ-E2E-secondary-device",
      });

        await gotoLoaded(page, baseURLValue, "/info/");
        const accountId = await page.evaluate(
          () => (window as typeof window & { index: { acct_id: number } }).index.acct_id,
        );
        expect(typeof accountId).toBe("number");

        await gotoLoaded(secondaryPage, baseURLValue, "/info/");
        await secondaryPage.waitForFunction(
          () =>
            (window as typeof window & { index: { ws: WebSocket } }).index.ws.readyState ===
            WebSocket.OPEN,
        );
        await secondaryPage.evaluate(() => {
          const appWindow = window as typeof window & {
            index: { ws: WebSocket };
            __e2eRemoteLogoutClosed?: boolean;
          };
          appWindow.__e2eRemoteLogoutClosed = false;
          appWindow.index.ws.addEventListener(
            "close",
            () => {
              appWindow.__e2eRemoteLogoutClosed = true;
            },
            { once: true },
          );
        });

        await gotoLoaded(page, baseURLValue, `/acctedit/${accountId}/`);
        const sessionRows = page.locator("#loginlist tbody tr");
        await expect(sessionRows).toHaveCount(2);
        const secondaryRow = sessionRows.filter({
          hasText: "NTOJ-E2E-secondary-device",
        });
        await expect(secondaryRow).toHaveCount(1);

        const responsePromise = page.waitForResponse(
          (response) =>
            response.url().endsWith("/be/acctedit") &&
            response.request().method() === "POST",
        );
        await secondaryRow.locator("button.logout").click();
        expect((await responseJson(await responsePromise)).status).toBe("S");

        await secondaryPage.waitForFunction(
          () =>
            (window as typeof window & { __e2eRemoteLogoutClosed?: boolean })
              .__e2eRemoteLogoutClosed === true,
        );
        await expect(page.locator("#indexNotifyDialog .modal-body")).toHaveText(
          "Log out Successfully",
        );
        await expect(
          page
            .locator("#loginlist tbody tr")
            .filter({ hasText: "NTOJ-E2E-secondary-device" }),
        ).toHaveCount(0);

    },
  );
});

test.describe("public shell and SPA", { tag: "@smoke" }, () => {
  const pages: Array<[string, string, string?]> = [
    ["/info/", "#index-cont h1", "公告"],
    ["/proset/", "#prolist"],
    ["/chal/", "#challist"],
    ["/contests/", "#index-cont h4", "Active Contests"],
    ["/about/", "#index-cont", "TOJ開発者"],
  ];

  for (const [path, selector, text] of pages) {
    test(`public page loads: ${path}`, async ({ page, baseURLValue }) => {
      await gotoLoaded(page, baseURLValue, path);
      const locator = page.locator(selector);
      if (text) {
        await expect(locator.filter({ hasText: text }).first()).toBeVisible();
      } else {
        await expect(locator).toBeVisible();
      }
      if (path === "/info/") {
        await expect(
          page.locator('script[src="/src/third/jquery-3.7.1.min.js"]'),
        ).toHaveCount(1);
        await expect(
          page.locator('link[href="/src/third/bootstrap-5.3.2.min.css"]'),
        ).toHaveCount(1);
        await expect(
          page.locator('script[src="/src/third/popper-2.11.8.min.js"]'),
        ).toHaveCount(1);
        await expect(
          page.locator('script[src="/src/third/bootstrap-5.3.2.min.js"]'),
        ).toHaveCount(1);
        const jqueryVersion = await page.evaluate(
          () =>
            (window as typeof window & {
              jQuery?: { fn: { jquery: string } };
            }).jQuery?.fn.jquery,
        );
        expect(jqueryVersion).toBe("3.7.1");
        const bootstrapVersion = await page.evaluate(
          () =>
            (window as typeof window & {
              bootstrap?: { Modal: { VERSION: string } };
            }).bootstrap?.Modal.VERSION,
        );
        expect(bootstrapVersion).toBe("5.3.2");
      }
    });
  }

  test("guest navigation uses SPA fragment loading", async ({ page, baseURLValue }) => {
    await gotoLoaded(page, baseURLValue, "/info/");
    await page.locator("#index-navlist li.proset a").click();
    await page.waitForURL(appUrl(baseURLValue, "/proset/"));
    await expect(page.locator("#prolist")).toBeVisible();
    await waitForContainer(page);

    await page.locator("#index-navlist li.contests a").click();
    await page.waitForURL(appUrl(baseURLValue, "/contests/"));
    await expect(
      page.locator("#index-cont h4").filter({ hasText: "Active Contests" }),
    ).toBeVisible();
    await waitForContainer(page);
  });

  test("guest navigation exposes auth but not management", async ({
    page,
    baseURLValue,
  }) => {
    await gotoLoaded(page, baseURLValue, "/info/");
    await expect(page.locator("#index-navlist li.sign")).toBeVisible();
    await expect(page.locator("#index-navlist a.account")).toBeHidden();
    await expect(page.locator("#index-navlist li.manage")).toHaveCount(0);
  });
});

test.describe("standard workflows", { tag: "@standard" }, () => {
  test("problem-set filter updates the SPA", async ({ page, baseURLValue }) => {
    const search = uniqueText("no-such-problem");
    await gotoLoaded(page, baseURLValue, "/proset/");
    await page.locator("#filter #name").fill(search);

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/be/proset") && response.request().method() === "GET",
    );
    await page.locator("#filter_submit").click();
    await responsePromise;

    await page.waitForURL((url) => url.searchParams.get("name") === search);
    await expect(page.locator("#filter #name")).toHaveValue(search);
    await expect(page.locator("#prolist")).toBeVisible();
    await waitForContainer(page);
  });

  test("user can update profile through the UI", async ({
    page,
    signedInUser,
    baseURLValue,
  }) => {
    const motto = uniqueText("motto");
    await gotoLoaded(page, baseURLValue, "/info/");
    const accountId = await page.evaluate(
      () => (window as typeof window & { index: { acct_id: number } }).index.acct_id,
    );
    await gotoLoaded(page, baseURLValue, `/acctedit/${accountId}/`);
    await page.locator("#profile input.motto").fill(motto);

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/be/acctedit") &&
        response.request().method() === "POST",
    );
    await page.locator("#profile button.submit").click();
    expect((await responseJson(await responsePromise)).status).toBe("S");
    await expect(page.locator("#indexNotifyDialog .modal-body")).toHaveText(
      "Update Successfully",
    );

    await gotoLoaded(page, baseURLValue, `/acct/${accountId}/`);
    await expect(page.locator("#profile p").filter({ hasText: motto })).toBeVisible();
  });

  test("user can ask and remove a question", async ({
    page,
    context,
    signedInUser,
    baseURLValue,
  }) => {
    const question = uniqueText("question");
    await gotoLoaded(page, baseURLValue, "/question/");
    await page.locator("#form textarea.ques").fill(question);

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/be/question") &&
        response.request().method() === "POST",
    );
    await page.locator("#form button.submit").click();
    expect((await responseJson(await responsePromise)).status).toBe("S");

    await reloadLoaded(page);
    await expect(page.getByText(question, { exact: true })).toBeVisible();

    const cleanup = await context.request.post(appUrl(baseURLValue, "/be/question"), {
      form: { reqtype: "rm_ques", index: "0" },
    });
    await assertApiSuccess(cleanup, "remove E2E question");
    await reloadLoaded(page);
    await expect(page.getByText(question, { exact: true })).toHaveCount(0);
  });

});
