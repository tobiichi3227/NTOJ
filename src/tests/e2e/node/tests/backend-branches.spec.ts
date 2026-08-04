import { APIRequestContext, APIResponse } from "@playwright/test";
import { test, expect } from "../src/fixtures";
import {
  appUrl,
  configureContest,
  createContest,
  dateFromNow,
  gotoLoaded,
  responseJson,
  uniqueText,
} from "../src/helpers";
import { exposeSeedJudgeProblem } from "../src/judge";

async function expectStatus(
  response: APIResponse,
  expected: string,
): Promise<Record<string, unknown>> {
  expect(response.ok(), `HTTP ${response.status()} from ${response.url()}`).toBeTruthy();
  const payload = await responseJson(response);
  expect(payload.status, JSON.stringify(payload)).toBe(expected);
  return payload;
}

async function postForm(
  api: APIRequestContext,
  baseURL: string,
  path: string,
  form: Record<string, string>,
): Promise<Record<string, unknown>> {
  return responseJson(await api.post(appUrl(baseURL, path), { form }));
}

test.describe("backend validation branches", { tag: "@branches" }, () => {
  test("guest problem and challenge filters reject malformed values and execute every ordering", async ({
    context,
    baseURLValue,
  }) => {
    const api = context.request;
    const invalidGets: Array<[string, string]> = [
      ["/be/proset?pageoff=not-a-number", "Eparam"],
      ["/be/proset?proclass_id=not-a-number", "Eparam"],
      ["/be/proset?topcoder=0", "Eparam"],
      ["/be/chal?pageoff=not-a-number", "Eparam"],
      ["/be/chal?state=not-a-number", "Eparam"],
      ["/be/chal?state=999", "Eparam"],
      ["/be/chal?compiler_type=not-a-number", "Eparam"],
      ["/be/chal?compiler_type=999", "Eparam"],
    ];
    for (const [path, status] of invalidGets) {
      await expectStatus(await api.get(appUrl(baseURLValue, path)), status);
    }

    const successfulProblemQueries = [
      "/be/proset?pageoff=-10",
      "/be/proset?show=onlyac",
      "/be/proset?show=notac",
      "/be/proset?online=true",
      "/be/proset?name=GCD",
      "/be/proset?tags=missing",
      "/be/proset?topcoder=ignore&reverse=true",
      ...["chal", "user", "chalcnt", "chalaccnt", "usercnt", "useraccnt"].map(
        (order) => `/be/proset?order=${order}`,
      ),
    ];
    for (const path of successfulProblemQueries) {
      const response = await api.get(appUrl(baseURLValue, path));
      expect(response.ok(), path).toBeTruthy();
      expect(await response.text(), path).toContain("prolist");
    }

    const challengeResponse = await api.get(
      appUrl(
        baseURLValue,
        "/be/chal?pageoff=-10&state=0&compiler_type=-1&proid=1,invalid,2&acctid=1,2",
      ),
    );
    expect(challengeResponse.ok()).toBeTruthy();
    expect(await challengeResponse.text()).toContain("challist");

    for (const proclassType of ["official", "shared", "collection", "own"]) {
      await expectStatus(
        await api.post(appUrl(baseURLValue, "/be/proset"), {
          form: { reqtype: "listproclass", proclass_type: proclassType },
        }),
        "S",
      );
    }
    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/proset"), {
        form: { reqtype: "listproclass", proclass_type: "invalid" },
      }),
      "Eparam",
    );
    for (const reqtype of ["collect", "decollect"]) {
      await expectStatus(
        await api.post(appUrl(baseURLValue, "/be/proset"), {
          form: { reqtype, proclass_id: "1" },
        }),
        "Eacces",
      );
    }
  });

  test("signed-in account actions cover permission, validation, collection, and user ProClass lifecycles", async ({
    page,
    context,
    signedInUser: _signedInUser,
    baseURLValue,
  }) => {
    await gotoLoaded(page, baseURLValue, "/info/");
    const accountId = await page.evaluate(
      () => (window as typeof window & { index: { acct_id: number } }).index.acct_id,
    );
    const api = context.request;

    for (const reqtype of ["signin", "signup"]) {
      await expectStatus(
        await api.post(appUrl(baseURLValue, "/be/sign"), {
          form: {
            reqtype,
            mail: "already-signed-in@example.test",
            pw: "irrelevant-password",
            name: "already-signed-in",
          },
        }),
        "Esign",
      );
    }

    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/acctedit"), {
        form: { reqtype: "unknown-action", acct_id: String(accountId) },
      }),
      "Eunk",
    );
    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/acctedit"), {
        form: { reqtype: "profile", acct_id: "not-a-number", name: "x", photo: "", cover: "", motto: "" },
      }),
      "Eparam",
    );

    const otherAccount = String(accountId + 100_000);
    const deniedActions: Array<Record<string, string>> = [
      { reqtype: "profile", name: "x", photo: "", cover: "", motto: "" },
      { reqtype: "reset", old: "old", pw: "new-password" },
      { reqtype: "remote-logout", hashed_session_key: "missing" },
      { reqtype: "remote-logout-all" },
    ];
    for (const action of deniedActions) {
      await expectStatus(
        await api.post(appUrl(baseURLValue, "/be/acctedit"), {
          form: { ...action, acct_id: otherAccount },
        }),
        "Eacces",
      );
    }

    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/acctedit"), {
        form: {
          reqtype: "profile",
          acct_id: String(accountId),
          name: "",
          photo: "",
          cover: "",
          motto: "",
        },
      }),
      "Enamemin",
    );
    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/acctedit"), {
        form: {
          reqtype: "reset",
          acct_id: String(accountId),
          old: "definitely-wrong",
          pw: "new-password-123",
        },
      }),
      "Epwold",
    );
    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/acctedit"), {
        form: {
          reqtype: "remote-logout",
          acct_id: String(accountId),
          hashed_session_key: "missing-session",
        },
      }),
      "Enoext",
    );

    const proclassPath = `/be/acct/proclass/${accountId}`;
    const invalidAdds: Array<[Record<string, string>, string]> = [
      [{ reqtype: "add", type: "bad", list: "1", name: "valid", desc: "" }, "Eparam"],
      [{ reqtype: "add", type: "0", list: "1", name: "valid", desc: "" }, "Eparam"],
      [{ reqtype: "add", type: "2", list: "", name: "valid", desc: "" }, "Eparam"],
      [{ reqtype: "add", type: "2", list: "1", name: "", desc: "" }, "Eparam"],
      [{ reqtype: "add", type: "2", list: "1", name: "valid", desc: "x".repeat(2049) }, "Eparam"],
    ];
    for (const [form, status] of invalidAdds) {
      await expectStatus(
        await api.post(appUrl(baseURLValue, proclassPath), { form }),
        status,
      );
    }

    const name = uniqueText("user-proclass");
    const created = await expectStatus(
      await api.post(appUrl(baseURLValue, proclassPath), {
        form: { reqtype: "add", type: "2", list: "1", name, desc: "branch lifecycle" },
      }),
      "S",
    );
    const proclassId = Number(created.data);
    expect(Number.isSafeInteger(proclassId)).toBeTruthy();

    for (const pageName of [undefined, "add", "update"] as const) {
      const suffix =
        pageName === undefined
          ? ""
          : `?page=${pageName}${pageName === "update" ? `&proclassid=${proclassId}` : ""}`;
      const response = await api.get(appUrl(baseURLValue, `${proclassPath}${suffix}`));
      expect(response.ok()).toBeTruthy();
    }
    await expectStatus(
      await api.get(appUrl(baseURLValue, `${proclassPath}?page=update&proclassid=bad`)),
      "Eparam",
    );

    const invalidUpdates: Array<Record<string, string>> = [
      { reqtype: "update", proclass_id: "bad", type: "2", list: "1", name, desc: "" },
      { reqtype: "update", proclass_id: String(proclassId), type: "bad", list: "1", name, desc: "" },
      { reqtype: "update", proclass_id: String(proclassId), type: "2", list: "", name, desc: "" },
      { reqtype: "update", proclass_id: String(proclassId), type: "2", list: "1", name: "", desc: "" },
    ];
    for (const form of invalidUpdates) {
      await expectStatus(
        await api.post(appUrl(baseURLValue, proclassPath), { form }),
        "Eparam",
      );
    }

    const updatedName = `${name}-updated`;
    await expectStatus(
      await api.post(appUrl(baseURLValue, proclassPath), {
        form: {
          reqtype: "update",
          proclass_id: String(proclassId),
          type: "3",
          list: "1",
          name: updatedName,
          desc: "updated",
        },
      }),
      "S",
    );

    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/proset"), {
        form: { reqtype: "collect", proclass_id: "bad" },
      }),
      "Eparam",
    );
    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/proset"), {
        form: { reqtype: "collect", proclass_id: String(proclassId) },
      }),
      "S",
    );
    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/proset"), {
        form: { reqtype: "collect", proclass_id: String(proclassId) },
      }),
      "Eexist",
    );
    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/proset"), {
        form: { reqtype: "decollect", proclass_id: "bad" },
      }),
      "Eparam",
    );
    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/proset"), {
        form: { reqtype: "decollect", proclass_id: String(proclassId + 100_000) },
      }),
      "Enoext",
    );
    await expectStatus(
      await api.post(appUrl(baseURLValue, "/be/proset"), {
        form: { reqtype: "decollect", proclass_id: String(proclassId) },
      }),
      "S",
    );

    await expectStatus(
      await api.post(appUrl(baseURLValue, proclassPath), {
        form: { reqtype: "remove", proclass_id: "bad" },
      }),
      "Eparam",
    );
    await expectStatus(
      await api.post(appUrl(baseURLValue, proclassPath), {
        form: { reqtype: "remove", proclass_id: String(proclassId) },
      }),
      "S",
    );
  });

  test("contest problem administration covers bulk, scoring, publish, rejudge, and system-test branches", async ({
    context,
    signedInAdmin: _signedInAdmin,
    baseURLValue,
  }) => {
    const api = context.request;
    // A clean deployment database seeds problem 1 as Hidden. This test owns
    // its prerequisite and promotes it through the real administrator API.
    await exposeSeedJudgeProblem(api, baseURLValue);
    const contest = await createContest(api, baseURLValue, {
      prefix: "branch-contest-pro",
      start: dateFromNow({ hours: 1 }),
      end: dateFromNow({ hours: 2 }),
      publicScoreboard: true,
    });
    const path = `/be/contests/${contest.contestId}/manage/pro`;
    const action = (form: Record<string, string>) => postForm(api, baseURLValue, path, form);
    const expectAction = async (form: Record<string, string>, status: string) => {
      const payload = await action(form);
      expect(payload.status, JSON.stringify(payload)).toBe(status);
      return payload;
    };

    await expectAction({ reqtype: "add", pro_id: "bad", score_type: "1" }, "Eparam");
    await expectAction({ reqtype: "add", pro_id: "1", score_type: "bad" }, "Eparam");
    await expectAction({ reqtype: "add", pro_id: "1", score_type: "99" }, "Eparam");
    await expectAction({ reqtype: "add", pro_id: "1", score_type: "1" }, "S");
    await expectAction({ reqtype: "add", pro_id: "1", score_type: "1" }, "Eexist");

    await expectAction({ reqtype: "update_score_type", pro_id: "999999", score_type: "0" }, "Enoext");
    await expectAction({ reqtype: "update_score_type", pro_id: "1", score_type: "99" }, "Eparam");
    await expectAction({ reqtype: "update_score_type", pro_id: "1", score_type: "0" }, "S");
    await expectAction({ reqtype: "update_challenge_style", pro_id: "999999", challenge_style: "1" }, "Enoext");
    await expectAction({ reqtype: "update_challenge_style", pro_id: "1", challenge_style: "99" }, "Eparam");
    await expectAction({ reqtype: "update_challenge_style", pro_id: "1", challenge_style: "2" }, "S");

    await expectAction({ reqtype: "multi_add", pro_id: "999998,999999", score_type: "1" }, "S");
    await expectAction({ reqtype: "multi_add", pro_id: "1", score_type: "99" }, "Eparam");
    const removed = await expectAction({ reqtype: "multi_remove", pro_id: "1,999999" }, "S");
    expect(String(removed.data)).toContain("Failed to remove: [999999]");
    await expectAction({ reqtype: "remove", pro_id: "1" }, "Enoext");
    await expectAction({ reqtype: "add", pro_id: "1", score_type: "1" }, "S");

    await expectAction({ reqtype: "rechal", pro_id: "bad" }, "Eparam");
    await expectAction({ reqtype: "rechal", pro_id: "999999" }, "Enoext");
    await expectAction({ reqtype: "rechal", pro_id: "1" }, "S");
    await expectAction({ reqtype: "public", pro_id: "999999" }, "Enoext");
    await expectAction({ reqtype: "public", pro_id: "1" }, "Etime");
    await expectAction({ reqtype: "system_test", pro_id: "999999" }, "Enoext");
    await expectAction({ reqtype: "system_test", pro_id: "1" }, "Econf");

    await configureContest(api, baseURLValue, contest, {
      start: dateFromNow({ hours: -2 }),
      end: dateFromNow({ hours: -1 }),
      regEnd: dateFromNow({ hours: -2 }),
      publicScoreboard: true,
      enableSystemTest: true,
    });
    await expectAction({ reqtype: "system_test", pro_id: "1" }, "Enoext");
    await expectAction({ reqtype: "public", pro_id: "1" }, "S");
    await expectAction({ reqtype: "remove", pro_id: "1" }, "S");
  });
});

