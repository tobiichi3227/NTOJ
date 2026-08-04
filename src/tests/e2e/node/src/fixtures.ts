import {
  APIRequestContext,
  BrowserContext,
  BrowserContextOptions,
  Page,
  test as base,
  expect,
} from "@playwright/test";
import {
  UserIdentity,
  gotoLoaded,
  loginApi,
  signoutApi,
  signupViaApi,
  uniqueIdentity,
} from "./helpers";
import { BrowserCoverageSession } from "./coverage";

type AdminCredentials = {
  email: string;
  password: string;
};

export type UserSession = {
  context: BrowserContext;
  page: Page;
  accountId: number;
  user: UserIdentity;
};

type BrowserDiagnostics = {
  track(context: BrowserContext): Promise<void>;
  finish(context: BrowserContext): Promise<void>;
};

type NewTrackedContext = (
  options?: BrowserContextOptions,
) => Promise<BrowserContext>;

export type NewUserSession = (
  user: UserIdentity,
  options?: BrowserContextOptions,
) => Promise<UserSession>;

type Fixtures = {
  baseURLValue: string;
  identity: UserIdentity;
  e2eUser: UserIdentity;
  signedInUser: UserIdentity;
  adminCredentials: AdminCredentials;
  signedInAdmin: AdminCredentials;
  adminApi: APIRequestContext;
  browserDiagnostics: BrowserDiagnostics;
  newTrackedContext: NewTrackedContext;
  newUserSession: NewUserSession;
};

const knownBrowserErrors = [
  "pdfjs-dist@4.7.76/+esm",
  "pdfjsLib is not defined",
];
const cancellableAsyncScripts = [
  "cdn.jsdelivr.net/npm/mathjax@",
];

export const test = base.extend<Fixtures>({
  baseURLValue: [
    async ({}, use) => {
      await use((process.env.NTOJ_E2E_BASE_URL ?? "http://127.0.0.1:5502").replace(/\/+$/, ""));
    },
    { scope: "test" },
  ],

  identity: async ({}, use) => {
    await use(uniqueIdentity());
  },

  e2eUser: async ({ playwright, baseURLValue }, use) => {
    const user = uniqueIdentity();
    const api = await playwright.request.newContext();
    await signupViaApi(api, baseURLValue, user);
    await signoutApi(api, baseURLValue);
    await api.dispose();
    await use(user);
  },

  signedInUser: async ({ context, e2eUser, baseURLValue }, use) => {
    await loginApi(context.request, baseURLValue, e2eUser.email, e2eUser.password);
    await use(e2eUser);
    await signoutApi(context.request, baseURLValue);
  },

  adminCredentials: async ({}, use, testInfo) => {
    const email = process.env.NTOJ_E2E_ADMIN_EMAIL;
    const password = process.env.NTOJ_E2E_ADMIN_PASSWORD;
    testInfo.skip(
      !email || !password,
      "Set NTOJ_E2E_ADMIN_EMAIL and NTOJ_E2E_ADMIN_PASSWORD to run admin E2E tests",
    );
    await use({ email: email!, password: password! });
  },

  signedInAdmin: async ({ context, adminCredentials, baseURLValue }, use) => {
    await loginApi(
      context.request,
      baseURLValue,
      adminCredentials.email,
      adminCredentials.password,
    );
    await use(adminCredentials);
    await signoutApi(context.request, baseURLValue);
  },

  adminApi: async ({ playwright, adminCredentials, baseURLValue }, use) => {
    const api = await playwright.request.newContext();
    await loginApi(api, baseURLValue, adminCredentials.email, adminCredentials.password);
    await use(api);
    await signoutApi(api, baseURLValue);
    await api.dispose();
  },

  browserDiagnostics: [
    async ({ context, page, baseURLValue }, use, testInfo) => {
      const errors: string[] = [];
      const abortedGets: Array<{ key: string; message: string }> = [];
      const successfulGets = new Set<string>();
      const trackedPages = new WeakSet<Page>();
      const trackedContexts = new WeakSet<BrowserContext>();
      const coverage = new BrowserCoverageSession(baseURLValue, testInfo);

      const trackPage = (page: Page): void => {
        if (trackedPages.has(page)) return;
        trackedPages.add(page);
        page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
        page.on("console", (message) => {
          if (message.type() === "error") errors.push(`console: ${message.text()}`);
        });
        page.on("response", (response) => {
          const request = response.request();
          if (
            request.method() === "GET" &&
            ["xhr", "fetch"].includes(request.resourceType()) &&
            response.ok()
          ) {
            successfulGets.add(`${request.method()} ${new URL(request.url()).pathname}`);
          }
        });
        page.on("requestfailed", (request) => {
          if (!["document", "script", "xhr", "fetch"].includes(request.resourceType())) return;
          const failure = request.failure()?.errorText ?? "unknown failure";
          if (
            failure === "net::ERR_ABORTED" &&
            cancellableAsyncScripts.some((part) => request.url().includes(part))
          ) {
            return;
          }
          const message = `requestfailed: ${request.method()} ${request.url()}: ${failure}`;
          if (
            failure === "net::ERR_ABORTED" &&
            request.method() === "GET" &&
            ["xhr", "fetch"].includes(request.resourceType())
          ) {
            abortedGets.push({
              key: `${request.method()} ${new URL(request.url()).pathname}`,
              message,
            });
            return;
          }
          errors.push(message);
        });
      };

      const track = async (trackedContext: BrowserContext): Promise<void> => {
        if (trackedContexts.has(trackedContext)) return;
        trackedContexts.add(trackedContext);
        trackedContext.pages().forEach(trackPage);
        trackedContext.on("page", trackPage);
        await coverage.trackContext(trackedContext);
      };

      await track(context);
      await use({
        track,
        finish: (trackedContext) => coverage.finishContext(trackedContext),
      });
      await coverage.finishContext(context);
      await coverage.writeRawCoverage();

      const configured = (process.env.NTOJ_E2E_ALLOWED_BROWSER_ERRORS ?? "")
        .split("||")
        .map((value) => value.trim())
        .filter(Boolean);
      const annotations = testInfo.annotations
        .filter((annotation) => annotation.type === "allow-browser-error")
        .flatMap((annotation) => (annotation.description ? [annotation.description] : []));
      const allowed = [...knownBrowserErrors, ...configured, ...annotations];
      const unrecoveredAborts = abortedGets
        .filter(({ key }) => !successfulGets.has(key))
        .map(({ message }) => message);
      const unexpected = [...errors, ...unrecoveredAborts].filter(
        (error) => !allowed.some((allowedText) => error.includes(allowedText)),
      );
      expect(unexpected, `Unexpected browser errors:\n${unexpected.join("\n")}`).toEqual([]);
    },
    { auto: true },
  ],

  newTrackedContext: async (
    { browser, baseURLValue, browserDiagnostics },
    use,
  ) => {
    const contexts: BrowserContext[] = [];
    await use(async (options = {}) => {
      const trackedContext = await browser.newContext({
        baseURL: baseURLValue,
        viewport: { width: 1440, height: 1000 },
        locale: "zh-TW",
        timezoneId: "Asia/Taipei",
        ...options,
      });
      contexts.push(trackedContext);
      await browserDiagnostics.track(trackedContext);
      return trackedContext;
    });
    await Promise.all(
      contexts.map(async (trackedContext) => {
        await browserDiagnostics.finish(trackedContext);
        await trackedContext.close();
      }),
    );
  },

  newUserSession: async (
    { newTrackedContext, baseURLValue, browserDiagnostics },
    use,
  ) => {
    const sessions: UserSession[] = [];
    await use(async (user, options = {}) => {
      const sessionContext = await newTrackedContext(options);
      await loginApi(sessionContext.request, baseURLValue, user.email, user.password);
      const sessionPage = await sessionContext.newPage();
      await gotoLoaded(sessionPage, baseURLValue, "/info/");
      const accountId = await sessionPage.evaluate(
        () => (window as typeof window & { index: { acct_id: number } }).index.acct_id,
      );
      const session = {
        context: sessionContext,
        page: sessionPage,
        accountId,
        user,
      };
      sessions.push(session);
      return session;
    });
    await Promise.all(
      sessions.map(async (session) => {
        await browserDiagnostics.finish(session.context);
        await Promise.all(session.context.pages().map((page) => page.close()));
        await signoutApi(session.context.request, baseURLValue);
      }),
    );
  },
});

export { expect } from "@playwright/test";
