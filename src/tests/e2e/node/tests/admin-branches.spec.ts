import { APIRequestContext, APIResponse } from "@playwright/test";
import { test, expect } from "../src/fixtures";
import { appUrl, responseJson } from "../src/helpers";

async function expectStatus(
  response: APIResponse,
  status: string,
): Promise<Record<string, unknown>> {
  expect(response.ok(), `HTTP ${response.status()} from ${response.url()}`).toBeTruthy();
  const payload = await responseJson(response);
  expect(payload.status, JSON.stringify(payload)).toBe(status);
  return payload;
}

async function post(
  api: APIRequestContext,
  baseURL: string,
  path: string,
  form: Record<string, string>,
  status: string,
): Promise<Record<string, unknown>> {
  return expectStatus(await api.post(appUrl(baseURL, path), { form }), status);
}

test.describe("administrator validation branches", { tag: ["@admin", "@branches"] }, () => {
  test("problem dispatchers, rejudge, limits, packages, and Judge controls reject invalid requests", async ({
    context,
    signedInAdmin: _signedInAdmin,
    baseURLValue,
  }) => {
    const api = context.request;

    await expectStatus(
      await api.get(appUrl(baseURLValue, "/be/manage/pro?pageoff=bad")),
      "Eparam",
    );
    const negativePage = await api.get(
      appUrl(baseURLValue, "/be/manage/pro?pageoff=-10"),
    );
    expect(negativePage.ok()).toBeTruthy();
    expect(await negativePage.text()).toContain("prolist");

    await post(api, baseURLValue, "/be/manage/pro", { reqtype: "unknown" }, "Eunk");
    await post(
      api,
      baseURLValue,
      "/be/manage/pro",
      { reqtype: "rechal", pro_id: "bad" },
      "Eparam",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/pro",
      { reqtype: "rechal", pro_id: "999999" },
      "Enoext",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/pro",
      { reqtype: "rechal", pro_id: "1" },
      "S",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/pro",
      { reqtype: "rechalall", pro_id: "1", pwd: "wrong-password" },
      "Eacces",
    );

    await post(
      api,
      baseURLValue,
      "/be/manage/pro/add",
      { reqtype: "unknown" },
      "Eunk",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/pro/add",
      { reqtype: "addpro", name: "invalid", status: "bad", mode: "manual", pack_token: "" },
      "Eparam",
    );

    await expectStatus(
      await api.get(appUrl(baseURLValue, "/be/manage/pro/update?proid=bad")),
      "Eparam",
    );
    await expectStatus(
      await api.get(appUrl(baseURLValue, "/be/manage/pro/update?proid=999999")),
      "Enoext",
    );
    await post(api, baseURLValue, "/be/manage/pro/update", { reqtype: "unknown" }, "Eunk");
    await post(
      api,
      baseURLValue,
      "/be/manage/pro/update",
      { reqtype: "updategeneral", pro_id: "bad", status: "0", name: "x", tags: "", allow_submit: "true" },
      "Eparam",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/pro/update",
      { reqtype: "updategeneral", pro_id: "1", status: "bad", name: "x", tags: "", allow_submit: "true" },
      "Eparam",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/pro/update",
      { reqtype: "updategeneral", pro_id: "999999", status: "0", name: "x", tags: "", allow_submit: "true" },
      "Enoext",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/pro/update",
      { reqtype: "uploadpackage", pro_id: "bad", pack_token: "missing" },
      "Eparam",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/pro/update",
      { reqtype: "uploadpackage", pro_id: "999999", pack_token: "missing" },
      "Enoext",
    );

    for (const path of [
      "/be/manage/pro/updatejudge",
      "/be/manage/pro/updatetestdata",
      "/be/manage/pro/filemanager",
    ]) {
      await expectStatus(
        await api.get(appUrl(baseURLValue, `${path}?proid=bad`)),
        "Eparam",
      );
      await expectStatus(
        await api.get(appUrl(baseURLValue, `${path}?proid=999999`)),
        "Enoext",
      );
      await post(api, baseURLValue, path, { pro_id: "bad", reqtype: "unknown" }, "Eparam");
      await post(api, baseURLValue, path, { pro_id: "999999", reqtype: "unknown" }, "Enoext");
    }

    await expectStatus(
      await api.get(appUrl(baseURLValue, "/be/manage/pro/updatelimit?proid=bad")),
      "Eparam",
    );
    await expectStatus(
      await api.get(appUrl(baseURLValue, "/be/manage/pro/updatelimit?proid=999999")),
      "Enoext",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/pro/updatelimit",
      { reqtype: "unknown" },
      "Eunk",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/pro/updatelimit",
      { reqtype: "updatelimit", pro_id: "bad", limits: "{}" },
      "Eparam",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/pro/updatelimit",
      { reqtype: "updatelimit", pro_id: "999999", limits: "{}" },
      "Enoext",
    );

    await post(api, baseURLValue, "/be/manage/judge", { reqtype: "unknown" }, "Eunk");
    await post(
      api,
      baseURLValue,
      "/be/manage/judge",
      { reqtype: "connect", index: "bad" },
      "Eparam",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/judge",
      { reqtype: "connect", index: "999999" },
      "Eparam",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/judge",
      { reqtype: "disconnect", index: "bad", pwd: "wrong" },
      "Eparam",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/judge",
      { reqtype: "disconnect", index: "999999", pwd: "wrong" },
      "Eparam",
    );
    await post(
      api,
      baseURLValue,
      "/be/manage/judge",
      { reqtype: "disconnect", index: "0", pwd: "wrong" },
      "Eacces",
    );
  });

  test("authenticated source and report handlers validate malformed and missing challenge IDs", async ({
    context,
    signedInAdmin: _signedInAdmin,
    baseURLValue,
  }) => {
    await post(
      context.request,
      baseURLValue,
      "/be/code",
      { chal_id: "bad" },
      "Eparam",
    );
    await post(
      context.request,
      baseURLValue,
      "/be/code",
      { chal_id: "999999" },
      "Enoext",
    );
    await expectStatus(
      await context.request.get(appUrl(baseURLValue, "/be/report?chal_id=bad")),
      "Eparam",
    );
    const report = await context.request.get(
      appUrl(baseURLValue, "/be/report?chal_id=1"),
    );
    expect(report.ok()).toBeTruthy();
    expect(await report.text()).toContain("題目問題回報");
  });
});

