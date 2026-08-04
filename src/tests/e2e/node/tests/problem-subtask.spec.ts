import {
  APIRequestContext,
  APIResponse,
  Page,
  Response,
} from "@playwright/test";
import { test, expect } from "../src/fixtures";
import {
  appUrl,
  assertApiSuccess,
  dismissNotification,
  gotoLoaded,
  responseJson,
  uniqueText,
} from "../src/helpers";

type HttpResponse = APIResponse | Response;

async function createManualProblem(
  api: APIRequestContext,
  baseURL: string,
): Promise<{ id: number; name: string }> {
  const name = uniqueText("subtask-config");
  const response = await api.post(appUrl(baseURL, "/be/manage/pro/add"), {
    form: {
      reqtype: "addpro",
      name,
      status: "2",
      mode: "manual",
      pack_token: "",
    },
  });
  const payload = await assertApiSuccess(response, `create Batch problem ${name}`);
  const id = Number(payload.data);
  expect(Number.isSafeInteger(id) && id > 0).toBeTruthy();
  return { id, name };
}

async function expectStatus(
  response: HttpResponse,
  status: string,
): Promise<Record<string, unknown>> {
  expect(response.ok(), `HTTP ${response.status()} from ${response.url()}`).toBeTruthy();
  const payload = await responseJson(response);
  expect(payload.status, JSON.stringify(payload)).toBe(status);
  return payload;
}

function waitForSubtaskPost(page: Page, reqtype: string): Promise<Response> {
  return page.waitForResponse((response) =>
    response.request().method() === "POST" &&
    response.url().endsWith("/be/manage/pro/updatesubtask") &&
    response.request().postData()?.includes(`reqtype=${reqtype}`) === true,
  );
}

async function leaveAndReturn(
  page: Page,
  baseURL: string,
  path: string,
): Promise<void> {
  await dismissNotification(page);
  await gotoLoaded(page, baseURL, "/info/");
  await gotoLoaded(page, baseURL, path);
}

async function uploadTestdata(
  page: Page,
  baseURL: string,
  path: string,
  name: string,
  input: string,
  output: string,
): Promise<void> {
  await page.getByRole("button", { name: "Add Single File" }).click();
  const modal = page.locator("#addSingleFileModal");
  await expect(modal).toBeVisible();
  await modal.locator("input.filename").fill(name);
  await modal.locator("input.inputfile").setInputFiles({
    name: `${name}.in`,
    mimeType: "text/plain",
    buffer: Buffer.from(input),
  });
  await modal.locator("input.outputfile").setInputFiles({
    name: `${name}.out`,
    mimeType: "text/plain",
    buffer: Buffer.from(output),
  });
  const responsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST" &&
    response.url().endsWith("/be/manage/pro/updatetestdata") &&
    response.request().postData()?.includes("reqtype=addsinglefile") === true,
  );
  await modal.getByRole("button", { name: "Upload" }).click();
  await expectStatus(await responsePromise, "S");
  await leaveAndReturn(page, baseURL, path);
}

async function addSubtask(
  page: Page,
  baseURL: string,
  path: string,
  rate: number,
): Promise<void> {
  page.once("dialog", (dialog) => void dialog.accept(String(rate)));
  const responsePromise = waitForSubtaskPost(page, "addsubtask");
  await page.locator("button.add-subtask").click();
  await expectStatus(await responsePromise, "S");
  await leaveAndReturn(page, baseURL, path);
}

async function expandSubtask(page: Page, subtaskId: number) {
  const section = page.locator(
    `#subtasks .accordion-collapse[subtask="${subtaskId}"]`,
  );
  if (!(await section.isVisible())) {
    await section
      .locator("xpath=..")
      .locator(":scope > .accordion-header .accordion-button")
      .click();
  }
  await expect(section).toBeVisible();
  return section;
}

test.describe("Batch problem subtasks", { tag: "@admin" }, () => {
  test.describe.configure({ timeout: 180_000 });

  test("subtask rates, cases, tags and dependencies persist while cycles are rejected", async ({
    page,
    context,
    signedInAdmin: _signedInAdmin,
    baseURLValue,
  }) => {
    const problem = await createManualProblem(context.request, baseURLValue);
    const testdataPath = `/manage/pro/updatetestdata/?proid=${problem.id}`;
    await gotoLoaded(page, baseURLValue, testdataPath);
    await uploadTestdata(
      page,
      baseURLValue,
      testdataPath,
      uniqueText("subtask-case-a"),
      "1 2\n",
      "3\n",
    );
    await uploadTestdata(
      page,
      baseURLValue,
      testdataPath,
      uniqueText("subtask-case-b"),
      "5 8\n",
      "13\n",
    );
    await expect(page.locator("tbody tr")).toHaveCount(2);

    const subtaskPath = `/manage/pro/updatesubtask/?proid=${problem.id}`;
    await gotoLoaded(page, baseURLValue, subtaskPath);
    await expect(page.locator("#subtasks .accordion-item")).toHaveCount(0);
    await addSubtask(page, baseURLValue, subtaskPath, 60);
    await addSubtask(page, baseURLValue, subtaskPath, 40);

    let headers = page.locator("#subtasks .accordion-button");
    await expect(headers).toHaveCount(2);
    await expect(headers.nth(0)).toContainText("Subtask 1 Rate: 60");
    await expect(headers.nth(1)).toContainText("Subtask 2 Rate: 40");

    let first = await expandSubtask(page, 0);
    await first.locator("#rate").fill("55");
    let responsePromise = waitForSubtaskPost(page, "updaterate");
    await first.locator("button.edit-rate").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, subtaskPath);
    await expect(page.locator("#subtasks .accordion-button").nth(0)).toContainText(
      "Subtask 1 Rate: 55",
    );

    first = await expandSubtask(page, 0);
    await first.locator("#testdatas").fill("1-2");
    responsePromise = waitForSubtaskPost(page, "settestdata");
    await first.locator("button.set-testdatas").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, subtaskPath);
    first = await expandSubtask(page, 0);
    await expect(first.locator("#testdatas")).toHaveValue("1-2");

    await first.locator("#metadata-tags").fill("sample, system-test, sample");
    responsePromise = waitForSubtaskPost(page, "updatemetadata");
    await first.locator("button.set-metadata-tags").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, subtaskPath);
    first = await expandSubtask(page, 0);
    await expect(first.locator("#metadata-tags")).toHaveValue(
      "sample,system-test,sample",
    );

    let second = await expandSubtask(page, 1);
    await second.locator("#testdatas").fill("2");
    responsePromise = waitForSubtaskPost(page, "settestdata");
    await second.locator("button.set-testdatas").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, subtaskPath);

    second = await expandSubtask(page, 1);
    await second.locator("#depsubtasks").fill("1");
    responsePromise = waitForSubtaskPost(page, "setdepsubtasks");
    await second.locator("button.set-depsubtasks").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, subtaskPath);
    second = await expandSubtask(page, 1);
    await expect(second.locator("#testdatas")).toHaveValue("2");
    await expect(second.locator("#depsubtasks")).toHaveValue("1");

    first = await expandSubtask(page, 0);
    await first.locator("#depsubtasks").fill("2");
    responsePromise = waitForSubtaskPost(page, "setdepsubtasks");
    await first.locator("button.set-depsubtasks").click();
    const cyclePayload = await expectStatus(await responsePromise, "Eparam");
    expect(cyclePayload.data).toBe("Dependency subtasks have cycle");
    await expect(page.locator("#indexNotifyDialog")).toContainText(
      "Dependency subtasks have cycle",
    );
    await leaveAndReturn(page, baseURLValue, subtaskPath);
    first = await expandSubtask(page, 0);
    await expect(first.locator("#depsubtasks")).toHaveValue("");
    second = await expandSubtask(page, 1);
    await expect(second.locator("#depsubtasks")).toHaveValue("1");

    await addSubtask(page, baseURLValue, subtaskPath, 10);
    headers = page.locator("#subtasks .accordion-button");
    await expect(headers).toHaveCount(3);
    await expect(headers.nth(2)).toContainText("Subtask 3 Rate: 10");

    second = await expandSubtask(page, 1);
    page.once("dialog", (dialog) => void dialog.accept());
    responsePromise = waitForSubtaskPost(page, "deletesubtask");
    await second.locator("button.delete-subtask").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, subtaskPath);
    headers = page.locator("#subtasks .accordion-button");
    await expect(headers).toHaveCount(2);
    await expect(headers.nth(0)).toContainText("Subtask 1 Rate: 55");
    await expect(headers.nth(1)).toContainText("Subtask 2 Rate: 10");
  });

  test("general settings publish a renamed problem and disable submissions", async ({
    page,
    context,
    signedInAdmin: _signedInAdmin,
    baseURLValue,
  }) => {
    const problem = await createManualProblem(context.request, baseURLValue);
    const generalPath = `/manage/pro/update/?proid=${problem.id}`;
    const renamed = uniqueText("published-problem");
    await gotoLoaded(page, baseURLValue, generalPath);

    await expect(
      page.getByRole("heading", {
        name: `Problem General Settings - ${problem.name}`,
      }),
    ).toBeVisible();
    await expect(page.locator("#status")).toHaveValue("2");
    await page.locator("#problemName").fill(renamed);
    await page.locator("#problemTags").fill("graph, shortest-path");
    await page.locator("#status").selectOption("0");
    await page.locator("#allow-submit").uncheck();

    page.once("dialog", (dialog) => void dialog.accept());
    const responsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/be/manage/pro/update") &&
      response.request().postData()?.includes("reqtype=updategeneral") === true,
    );
    await page.locator("#general button.submit").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, generalPath);

    await expect(page.locator("#problemName")).toHaveValue(renamed);
    await expect(page.locator("#problemTags")).toHaveValue(
      "graph, shortest-path",
    );
    await expect(page.locator("#status")).toHaveValue("0");
    await expect(page.locator("#allow-submit")).not.toBeChecked();

    const pageoff = Math.floor((problem.id - 1) / 40) * 40;
    await gotoLoaded(page, baseURLValue, `/manage/pro/?pageoff=${pageoff}`);
    const row = page.locator(`td.control[proid="${problem.id}"]`).locator("xpath=..");
    await expect(row).toHaveCount(1);
    await expect(row).toContainText(renamed);
    await expect(row.locator("td.status-online")).toHaveText("Online");
    await expect(row.locator(`a[href="/manage/pro/update/?proid=${problem.id}"]`)).toHaveCount(1);
  });
});
