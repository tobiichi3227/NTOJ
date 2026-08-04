import {
  APIRequestContext,
  APIResponse,
  Page,
  Response,
  expect,
} from "@playwright/test";
import { randomUUID } from "node:crypto";

export interface UserIdentity {
  name: string;
  email: string;
  password: string;
}

export interface ContestIdentity {
  contestId: number;
  name: string;
}

type JsonResponse = APIResponse | Response;

export function uniqueText(prefix: string): string {
  return `e2e-${prefix}-${randomUUID().replaceAll("-", "").slice(0, 10)}`;
}

export function uniqueIdentity(prefix = "user"): UserIdentity {
  const name = uniqueText(prefix);
  return {
    name,
    email: `${name}@example.test`,
    password: "E2e-password-123",
  };
}

export function appUrl(baseURL: string, path: string): string {
  return `${baseURL.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}

export async function responseJson(response: JsonResponse): Promise<Record<string, unknown>> {
  try {
    return (await response.json()) as Record<string, unknown>;
  } catch (error) {
    const body = await response.text();
    throw new Error(`Expected JSON from ${response.url()}, got: ${body.slice(0, 500)}`, {
      cause: error,
    });
  }
}

export async function assertApiSuccess(
  response: APIResponse,
  operation: string,
): Promise<Record<string, unknown>> {
  expect(response.ok(), `${operation} returned HTTP ${response.status()}`).toBeTruthy();
  const payload = await responseJson(response);
  expect(payload.status, `${operation} failed: ${JSON.stringify(payload)}`).toBe("S");
  return payload;
}

export async function signupViaApi(
  api: APIRequestContext,
  baseURL: string,
  user: UserIdentity,
): Promise<void> {
  const response = await api.post(appUrl(baseURL, "/be/sign"), {
    form: {
      reqtype: "signup",
      name: user.name,
      mail: user.email,
      pw: user.password,
    },
  });
  await assertApiSuccess(response, `sign up ${user.email}`);
}

export async function loginApi(
  api: APIRequestContext,
  baseURL: string,
  email: string,
  password: string,
): Promise<void> {
  const response = await api.post(appUrl(baseURL, "/be/sign"), {
    form: { reqtype: "signin", mail: email, pw: password },
  });
  await assertApiSuccess(response, `sign in ${email}`);
}

export async function signoutApi(api: APIRequestContext, baseURL: string): Promise<void> {
  const response = await api.post(appUrl(baseURL, "/be/sign"), {
    form: { reqtype: "signout" },
  });
  const payload = await responseJson(response);
  expect(["S", "Esign"]).toContain(payload.status);
}

export async function waitForContainer(page: Page): Promise<void> {
  await page.waitForFunction(
    () =>
      Boolean(
        (window as typeof window & { index?: { containerLoadDone?: boolean } }).index
          ?.containerLoadDone,
      ),
  );
}

export async function gotoLoaded(
  page: Page,
  baseURL: string,
  path: string,
): Promise<Response> {
  const response = await page.goto(appUrl(baseURL, path), {
    waitUntil: "domcontentloaded",
  });
  expect(response, `Navigation to ${path} did not produce a response`).not.toBeNull();
  expect(response?.ok(), `Navigation to ${path} returned HTTP ${response?.status()}`).toBeTruthy();
  await expect(page.locator("#index-cont")).toBeVisible();
  await waitForContainer(page);
  return response!;
}

export async function reloadLoaded(page: Page): Promise<Response> {
  const fragmentResponsePromise = page.waitForResponse((response) => {
    const request = response.request();
    return (
      request.method() === "GET" &&
      request.headers()["req-by-frontend"] === "true"
    );
  });
  const [response, fragmentResponse] = await Promise.all([
    page.reload({ waitUntil: "domcontentloaded" }),
    fragmentResponsePromise,
  ]);
  expect(response, "Reload did not produce a response").not.toBeNull();
  expect(response?.ok(), `Reload returned HTTP ${response?.status()}`).toBeTruthy();
  expect(
    fragmentResponse.ok(),
    `Reloaded SPA fragment returned HTTP ${fragmentResponse.status()}`,
  ).toBeTruthy();
  await expect(page.locator("#index-cont")).toBeVisible();
  await waitForContainer(page);
  return response!;
}

export async function dismissNotification(page: Page): Promise<void> {
  const dialog = page.locator("#indexNotifyDialog");
  try {
    await dialog.waitFor({ state: "visible", timeout: 1_000 });
  } catch {
    return;
  }
  await dialog.getByRole("button", { name: "Close" }).last().click();
  await dialog.waitFor({ state: "detached" });
}

export async function createContest(
  api: APIRequestContext,
  baseURL: string,
  options: {
    prefix: string;
    start: Date;
    end: Date;
    regMode?: number;
    regEnd?: Date;
    contestMode?: number;
    publicScoreboard?: boolean;
    hideAdmin?: boolean;
    enableSystemTest?: boolean;
  },
): Promise<ContestIdentity> {
  expect(options.start.getTime()).toBeLessThan(options.end.getTime());
  const name = uniqueText(options.prefix);
  const created = await api.post(appUrl(baseURL, "/be/contests/manage/add"), {
    form: { reqtype: "add", name },
  });
  const payload = await assertApiSuccess(created, `create contest ${name}`);
  const contest = { contestId: Number(payload.data), name };
  await configureContest(api, baseURL, contest, options);
  return contest;
}

export async function configureContest(
  api: APIRequestContext,
  baseURL: string,
  contest: ContestIdentity,
  options: {
    start: Date;
    end: Date;
    regMode?: number;
    regEnd?: Date;
    contestMode?: number;
    publicScoreboard?: boolean;
    hideAdmin?: boolean;
    enableSystemTest?: boolean;
  },
): Promise<void> {
  const contestMode = options.contestMode ?? 0;
  const body = new URLSearchParams([
    ["reqtype", "update"],
    ["name", contest.name],
    ["contest_mode", String(contestMode)],
    ["contest_start", options.start.toISOString()],
    ["contest_end", options.end.toISOString()],
    ["reg_mode", String(options.regMode ?? 0)],
    ["reg_end", (options.regEnd ?? options.end).toISOString()],
    ["allow_compilers[]", "3"],
    ["allow_compilers[]", "6"],
    ["is_public_scoreboard", String(options.publicScoreboard ?? true)],
    ["allow_view_other_page", "false"],
    ["hide_admin", String(options.hideAdmin ?? true)],
    ["submission_cd_time", contestMode === 0 ? "30" : "1"],
    ["freeze_scoreboard_period", "0"],
    ["penalty_value", "20"],
    ["enable_system_test", String(options.enableSystemTest ?? false)],
  ]);
  const response = await api.post(
    appUrl(baseURL, `/be/contests/${contest.contestId}/manage/general`),
    {
      data: body.toString(),
      headers: { "content-type": "application/x-www-form-urlencoded" },
    },
  );
  await assertApiSuccess(response, `configure contest ${contest.contestId}`);
}

export async function addContestMember(
  api: APIRequestContext,
  baseURL: string,
  contestId: number,
  accountId: number,
  memberType = "normal",
): Promise<void> {
  const response = await api.post(appUrl(baseURL, `/be/contests/${contestId}/manage/acct`), {
    form: {
      reqtype: "add",
      acct_id: String(accountId),
      type: memberType,
    },
  });
  await assertApiSuccess(
    response,
    `add ${memberType} account ${accountId} to contest ${contestId}`,
  );
}

export async function removeContestMember(
  api: APIRequestContext,
  baseURL: string,
  contestId: number,
  accountId: number,
  memberType = "normal",
): Promise<void> {
  const response = await api.post(appUrl(baseURL, `/be/contests/${contestId}/manage/acct`), {
    form: {
      reqtype: "remove",
      acct_id: String(accountId),
      type: memberType,
    },
  });
  await assertApiSuccess(
    response,
    `remove ${memberType} account ${accountId} from contest ${contestId}`,
  );
}


export function dateFromNow(options: {
  days?: number;
  hours?: number;
  milliseconds?: number;
}): Date {
  const offset =
    (options.days ?? 0) * 86_400_000 +
    (options.hours ?? 0) * 3_600_000 +
    (options.milliseconds ?? 0);
  return new Date(Date.now() + offset);
}
