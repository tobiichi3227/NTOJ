import { APIRequestContext, APIResponse, Page, Response } from "@playwright/test";
import { readFile } from "node:fs/promises";
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
  prefix: string,
): Promise<{ id: number; name: string }> {
  const name = uniqueText(prefix);
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

function waitForManagementPost(
  page: Page,
  endpoint: string,
  reqtype?: string,
): Promise<Response> {
  return page.waitForResponse((response) => {
    if (
      response.request().method() !== "POST" ||
      !response.url().endsWith(endpoint)
    ) {
      return false;
    }
    return reqtype === undefined || response.request().postData()?.includes(`reqtype=${reqtype}`) === true;
  });
}

async function leaveAndReturn(page: Page, baseURL: string, path: string): Promise<void> {
  await dismissNotification(page);
  await gotoLoaded(page, baseURL, "/info/");
  await gotoLoaded(page, baseURL, path);
}

test.describe("Batch problem management", { tag: "@admin" }, () => {
  test.describe.configure({ timeout: 120_000 });

  test("Judge and compiler limits reject invalid input and persist valid UI settings", async ({
    page,
    context,
    signedInAdmin: _signedInAdmin,
    baseURLValue,
  }) => {
    const problem = await createManualProblem(
      context.request,
      baseURLValue,
      "judge-config",
    );
    const judgePath = `/manage/pro/updatejudge/?proid=${problem.id}`;
    await gotoLoaded(page, baseURLValue, judgePath);

    await expect(
      page.getByRole("heading", {
        name: `Batch Problem Judge Configuration - ${problem.name}`,
      }),
    ).toBeVisible();
    await expect(page.locator("#checkerType")).toHaveValue("1");
    await expect(page.locator("#summaryType")).toHaveValue("1");

    await page.locator("#checkerType").selectOption("8");
    await expect(page.locator("#chalmetaLabel")).toBeVisible();
    await page.locator("#chalmeta").fill("{not valid json");
    let responsePromise = waitForManagementPost(
      page,
      "/be/manage/pro/updatejudge",
    );
    await page.locator("#judge button.submit").click();
    const invalidPayload = await expectStatus(await responsePromise, "Econf");
    expect(invalidPayload.data).toBe("Challenge metadata json syntax error");
    await expect(page.locator("#indexNotifyDialog")).toContainText(
      "Challenge metadata json syntax error",
    );
    await page.locator("#indexNotifyDialog .btn-close").click();
    await expect(page.locator("#indexNotifyDialog")).not.toBeVisible();

    await page.locator("#checkerType").selectOption("7");
    await expect(page.locator("#checkerCompilerLabel")).toBeVisible();
    await page.locator("#checkerCompiler").selectOption("3");
    await page.locator("#checkerCompileArgs").fill("-O2 -std=c++17");
    await page.locator("#summaryType").selectOption("3");
    await expect(page.locator("#summaryCompilerLabel")).toBeVisible();
    await page.locator("#summaryCompiler").selectOption("6");
    await page.locator("#summaryCompileArgs").fill("--summary-e2e");
    await page.locator("#has-grader").check();
    await page.locator("#userprogCompileArgs").fill("-DE2E_JUDGE_CONFIG=1");
    await page.locator("#score-precision").fill("3");

    const compilerCheckboxes = page.locator("#judge .compilers");
    for (let index = 0; index < (await compilerCheckboxes.count()); index += 1) {
      await compilerCheckboxes.nth(index).uncheck();
    }
    await page.locator('#judge .compilers[value="3"]').check();
    await page.locator('#judge .compilers[value="6"]').check();

    responsePromise = waitForManagementPost(page, "/be/manage/pro/updatejudge");
    await page.locator("#judge button.submit").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, judgePath);

    await expect(page.locator("#checkerType")).toHaveValue("7");
    await expect(page.locator("#checkerCompiler")).toHaveValue("3");
    await expect(page.locator("#checkerCompileArgs")).toHaveValue(
      "-O2 -std=c++17",
    );
    await expect(page.locator("#summaryType")).toHaveValue("3");
    await expect(page.locator("#summaryCompiler")).toHaveValue("6");
    await expect(page.locator("#summaryCompileArgs")).toHaveValue(
      "--summary-e2e",
    );
    await expect(page.locator("#has-grader")).toBeChecked();
    await expect(page.locator("#userprogCompileArgs")).toHaveValue(
      "-DE2E_JUDGE_CONFIG=1",
    );
    await expect(page.locator("#score-precision")).toHaveValue("3");
    await expect(page.locator('#judge .compilers[value="3"]')).toBeChecked();
    await expect(page.locator('#judge .compilers[value="6"]')).toBeChecked();
    await expect(page.locator('#judge .compilers[value="1"]')).not.toBeChecked();

    const limitsPath = `/manage/pro/updatelimit/?proid=${problem.id}`;
    await gotoLoaded(page, baseURLValue, limitsPath);
    const defaultRow = page.locator('#limits tbody tr[compiler="default"]');
    const gppRow = page.locator('#limits tbody tr[compiler="3"]');
    await defaultRow.locator("input.time").fill("1500");
    await defaultRow.locator("input.memory").fill("262144");
    await defaultRow.locator("input.output").fill("2048");
    await gppRow.locator("input.time").fill("750");
    await gppRow.locator("input.memory").fill("");
    await gppRow.locator("input.output").fill("1024");

    responsePromise = waitForManagementPost(
      page,
      "/be/manage/pro/updatelimit",
      "updatelimit",
    );
    await page.locator("#limits button.submit").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, limitsPath);

    await expect(defaultRow.locator("input.time")).toHaveValue("1500");
    await expect(defaultRow.locator("input.memory")).toHaveValue("262144");
    await expect(defaultRow.locator("input.output")).toHaveValue("2048");
    await expect(gppRow.locator("input.time")).toHaveValue("750");
    await expect(gppRow.locator("input.memory")).toHaveValue("262144");
    await expect(gppRow.locator("input.output")).toHaveValue("1024");

    const invalidLimits = await context.request.post(
      appUrl(baseURLValue, "/be/manage/pro/updatelimit"),
      {
        form: {
          reqtype: "updatelimit",
          pro_id: String(problem.id),
          limits: JSON.stringify({
            3: { time: 1, memory: 1, output: 1 },
          }),
        },
      },
    );
    const missingDefaultPayload = await expectStatus(invalidLimits, "Eparam");
    expect(missingDefaultPayload.data).toBe("Missing default limit config");
    await leaveAndReturn(page, baseURLValue, limitsPath);
    await expect(defaultRow.locator("input.time")).toHaveValue("1500");
    await expect(gppRow.locator("input.memory")).toHaveValue("262144");
  });

  test("testdata UI uploads, previews, downloads, updates metadata and deletes a case", async ({
    page,
    context,
    signedInAdmin: _signedInAdmin,
    baseURLValue,
  }) => {
    const problem = await createManualProblem(
      context.request,
      baseURLValue,
      "testdata-lifecycle",
    );
    const testdataPath = `/manage/pro/updatetestdata/?proid=${problem.id}`;
    const caseName = uniqueText("case");
    const originalInput = "2 < 3 & 5\n";
    const updatedInput = "updated input through pack websocket\n";
    const expectedOutput = "accepted output\n";
    await gotoLoaded(page, baseURLValue, testdataPath);
    await expect(page.locator("tbody tr")).toHaveCount(0);

    await page.getByRole("button", { name: "Add Single File" }).click();
    const addModal = page.locator("#addSingleFileModal");
    await expect(addModal).toBeVisible();
    await addModal.locator("input.filename").fill(caseName);
    await addModal.locator("input.inputfile").setInputFiles({
      name: `${caseName}.in`,
      mimeType: "text/plain",
      buffer: Buffer.from(originalInput),
    });
    await addModal.locator("input.outputfile").setInputFiles({
      name: `${caseName}.out`,
      mimeType: "text/plain",
      buffer: Buffer.from(expectedOutput),
    });
    let responsePromise = waitForManagementPost(
      page,
      "/be/manage/pro/updatetestdata",
      "addsinglefile",
    );
    await addModal.getByRole("button", { name: "Upload" }).click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, testdataPath);

    let row = page.locator('tbody tr[testdata_id="0"]');
    await expect(row).toHaveCount(1);
    await expect(row.locator("a.preview-file.input")).toHaveText(`${caseName}.in`);
    await expect(row.locator("a.preview-file.output")).toHaveText(`${caseName}.out`);

    responsePromise = waitForManagementPost(
      page,
      "/be/manage/pro/updatetestdata",
      "preview",
    );
    await row.locator("a.preview-file.input").click();
    const previewPayload = await expectStatus(await responsePromise, "S");
    expect(previewPayload.data).toBe("2 &lt; 3 &amp; 5\n");
    const previewModal = page.locator("#previewModal");
    await expect(previewModal).toBeVisible();
    await expect(previewModal.locator("code")).toHaveText(originalInput.trim());

    const downloadPromise = page.waitForEvent("download");
    await previewModal.getByRole("button", { name: "Download" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe(`${caseName}.in`);
    const downloadPath = await download.path();
    expect(downloadPath).not.toBeNull();
    expect(await readFile(downloadPath!, "utf8")).toBe(originalInput);
    await page.keyboard.press("Escape");
    await expect(previewModal).not.toBeVisible();

    await row.locator("#metadata-tags").fill("sample, system-test, sample");
    responsePromise = waitForManagementPost(
      page,
      "/be/manage/pro/updatetestdata",
      "updatemetadata",
    );
    await row.locator("button.update-metadata-tags").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, testdataPath);
    row = page.locator('tbody tr[testdata_id="0"]');
    await expect(row.locator("#metadata-tags")).toHaveValue(
      "sample,system-test,sample",
    );

    await row.locator("button.dropdown-toggle").click();
    const fileChooserPromise = page.waitForEvent("filechooser");
    await row.locator("button.update-single-file.input").click();
    const fileChooser = await fileChooserPromise;
    responsePromise = waitForManagementPost(
      page,
      "/be/manage/pro/updatetestdata",
      "updatesinglefile",
    );
    await fileChooser.setFiles({
      name: `${caseName}.in`,
      mimeType: "text/plain",
      buffer: Buffer.from(updatedInput),
    });
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, testdataPath);
    row = page.locator('tbody tr[testdata_id="0"]');

    const updatedPreview = await context.request.post(
      appUrl(baseURLValue, "/be/manage/pro/updatetestdata"),
      {
        form: {
          reqtype: "preview",
          pro_id: String(problem.id),
          testdata_id: "0",
          type: "input",
        },
      },
    );
    const updatedPayload = await expectStatus(updatedPreview, "S");
    expect(updatedPayload.data).toBe(updatedInput);

    page.once("dialog", (dialog) => dialog.accept());
    responsePromise = waitForManagementPost(
      page,
      "/be/manage/pro/updatetestdata",
      "deletesinglefile",
    );
    await row.locator("button.delete-single-file").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, testdataPath);
    await expect(page.locator("tbody tr")).toHaveCount(0);
  });

  test("file manager enforces safe paths across upload, update, rename and delete", async ({
    page,
    context,
    signedInAdmin: _signedInAdmin,
    baseURLValue,
  }) => {
    const problem = await createManualProblem(
      context.request,
      baseURLValue,
      "file-lifecycle",
    );
    const fileManagerPath = `/manage/pro/filemanager/?proid=${problem.id}`;
    const originalName = `${uniqueText("statement")}.txt`;
    const renamedName = originalName.replace(".txt", "-renamed.txt");
    const originalContent = "E2E statement file\nline two\n";
    const updatedContent = "Updated through the browser pack uploader\n";
    await gotoLoaded(page, baseURLValue, fileManagerPath);

    let httpSection = page.locator(".accordion-item").filter({
      hasText: `problem/${problem.id}/http`,
    });
    await httpSection.locator("button.accordion-button").click();
    await httpSection.getByRole("button", { name: "Add Single File" }).click();
    const addModal = page.locator("#addSingleFileModal");
    await expect(addModal).toBeVisible();
    await addModal.locator("input.filename").fill(originalName);
    await addModal.locator("input.file").setInputFiles({
      name: originalName,
      mimeType: "text/plain",
      buffer: Buffer.from(originalContent),
    });
    let responsePromise = waitForManagementPost(
      page,
      "/be/manage/pro/filemanager",
      "addsinglefile",
    );
    await addModal.getByRole("button", { name: "Upload" }).click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, fileManagerPath);

    httpSection = page.locator(".accordion-item").filter({
      hasText: `problem/${problem.id}/http`,
    });
    await httpSection.locator("button.accordion-button").click();
    let row = httpSection.locator(`tbody tr[filename="${originalName}"]`);
    await expect(row).toHaveCount(1);

    const preview = await context.request.post(
      appUrl(baseURLValue, "/be/manage/pro/filemanager"),
      {
        form: {
          reqtype: "preview",
          pro_id: String(problem.id),
          path: "http",
          filename: originalName,
        },
      },
    );
    expect((await expectStatus(preview, "S")).data).toBe(originalContent);

    const traversal = await context.request.post(
      appUrl(baseURLValue, "/be/manage/pro/filemanager"),
      {
        form: {
          reqtype: "preview",
          pro_id: String(problem.id),
          path: "http",
          filename: "../conf.json",
        },
      },
    );
    const traversalPayload = await expectStatus(traversal, "Eacces");
    expect(traversalPayload.data).toBe("Access denied: invalid file path");

    const invalidBasepath = await context.request.post(
      appUrl(baseURLValue, "/be/manage/pro/filemanager"),
      {
        form: {
          reqtype: "preview",
          pro_id: String(problem.id),
          path: "/etc",
          filename: "passwd",
        },
      },
    );
    expect((await expectStatus(invalidBasepath, "Eparam")).data).toBe(
      "Invalid basepath",
    );

    const downloaded = await context.request.get(
      appUrl(baseURLValue, "/be/manage/pro/filemanager"),
      {
        params: {
          proid: String(problem.id),
          download: "1",
          path: "http",
          filename: originalName,
        },
      },
    );
    expect(downloaded.ok()).toBeTruthy();
    expect(downloaded.headers()["content-disposition"]).toBe(
      `attachment; filename="${originalName}"`,
    );
    expect(await downloaded.text()).toBe(originalContent);

    const fileChooserPromise = page.waitForEvent("filechooser");
    await row.locator("button.update-single-file").click();
    const fileChooser = await fileChooserPromise;
    responsePromise = waitForManagementPost(
      page,
      "/be/manage/pro/filemanager",
      "updatesinglefile",
    );
    await fileChooser.setFiles({
      name: originalName,
      mimeType: "text/plain",
      buffer: Buffer.from(updatedContent),
    });
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, fileManagerPath);

    httpSection = page.locator(".accordion-item").filter({
      hasText: `problem/${problem.id}/http`,
    });
    await httpSection.locator("button.accordion-button").click();
    row = httpSection.locator(`tbody tr[filename="${originalName}"]`);
    const updatedPreview = await context.request.post(
      appUrl(baseURLValue, "/be/manage/pro/filemanager"),
      {
        form: {
          reqtype: "preview",
          pro_id: String(problem.id),
          path: "http",
          filename: originalName,
        },
      },
    );
    expect((await expectStatus(updatedPreview, "S")).data).toBe(updatedContent);

    page.once("dialog", (dialog) => dialog.accept(renamedName));
    responsePromise = waitForManagementPost(
      page,
      "/be/manage/pro/filemanager",
      "renamesinglefile",
    );
    await row.locator("button.rename-single-file").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, fileManagerPath);

    httpSection = page.locator(".accordion-item").filter({
      hasText: `problem/${problem.id}/http`,
    });
    await httpSection.locator("button.accordion-button").click();
    await expect(
      httpSection.locator(`tbody tr[filename="${originalName}"]`),
    ).toHaveCount(0);
    row = httpSection.locator(`tbody tr[filename="${renamedName}"]`);
    await expect(row).toHaveCount(1);

    page.once("dialog", (dialog) => dialog.accept());
    responsePromise = waitForManagementPost(
      page,
      "/be/manage/pro/filemanager",
      "deletesinglefile",
    );
    await row.locator("button.delete-single-file").click();
    await expectStatus(await responsePromise, "S");
    await leaveAndReturn(page, baseURLValue, fileManagerPath);
    httpSection = page.locator(".accordion-item").filter({
      hasText: `problem/${problem.id}/http`,
    });
    await httpSection.locator("button.accordion-button").click();
    await expect(
      httpSection.locator(`tbody tr[filename="${renamedName}"]`),
    ).toHaveCount(0);
  });
});
