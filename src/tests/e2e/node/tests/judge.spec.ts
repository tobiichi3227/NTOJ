import { test, expect } from "../src/fixtures";
import {
  addContestMember,
  appUrl,
  assertApiSuccess,
  createContest,
  dateFromNow,
  gotoLoaded,
  reloadLoaded,
  responseJson,
} from "../src/helpers";
import {
  addJudgeProblemToContest,
  CHALLENGE_STATE,
  GPP_COMPILER,
  HELLO_TOJ_AC,
  HELLO_TOJ_CE,
  HELLO_TOJ_WA,
  JUDGE_PROBLEM_ID,
  expectChallengeState,
  prepareJudgeProblem,
  readContestProblemScore,
  submitSourceFromUi,
} from "../src/judge";

test.describe("Judge core", { tag: "@judge" }, () => {
  test.describe.configure({ timeout: 120_000 });

  test.beforeEach(async ({ adminApi, baseURLValue }) => {
    await prepareJudgeProblem(adminApi, baseURLValue);
  });

  test("online Judge exposes the seeded G++ batch problem", async ({
    page,
    signedInUser,
    baseURLValue,
  }) => {
    await gotoLoaded(page, baseURLValue, `/pro/${JUDGE_PROBLEM_ID}/`);
    await expect(page.getByRole("heading", { name: /HelloTOJ/ })).toBeVisible();
    await page.getByRole("link", { name: "Submit", exact: true }).click();
    await page.waitForURL(appUrl(baseURLValue, `/submit/${JUDGE_PROBLEM_ID}/`));
    await expect(page.locator("#submit")).toBeVisible();
    await expect(page.locator("#compilerList")).toHaveValue(GPP_COMPILER);
    await expect(
      page.locator(`#compilerList option[value="${GPP_COMPILER}"]`),
    ).toContainText("G++ 14.2.0 GNU++17");
  });

  test("accepted solution reaches AC with full score and source", async ({
    page,
    signedInUser,
    baseURLValue,
  }) => {
    const challengeId = await submitSourceFromUi(page, baseURLValue, HELLO_TOJ_AC);
    await expectChallengeState(page, CHALLENGE_STATE.accepted);
    await expect(page.locator("#info")).toContainText(String(challengeId));
    await expect(page.locator("#info")).toContainText("G++ 14.2.0 GNU++17");
    await expect(page.locator("#testdatas td.state")).toHaveClass(/state-1/);
    await expect(page.locator("#code code")).toContainText("Hello, TOJ!");

    await gotoLoaded(
      page,
      baseURLValue,
      `/chal/?proid=${JUDGE_PROBLEM_ID}&state=1`,
    );
    const row = page.locator(`#chal${challengeId}`);
    await expect(row).toHaveCount(1);
    await expect(row.locator("#state")).toHaveText("Accepted");
    await expect(row.locator("#score")).toHaveText("100");
  });

  test("incorrect output reaches WA with zero score", async ({
    page,
    signedInUser,
    baseURLValue,
  }) => {
    await submitSourceFromUi(page, baseURLValue, HELLO_TOJ_WA);
    await expectChallengeState(page, CHALLENGE_STATE.wrongAnswer);
    await expect(page.locator("#testdatas td.state")).toHaveClass(/state-3/);
    await expect(page.locator("#testdatas td.state")).toHaveText("Wrong Answer");
  });

  test("invalid C++ reaches CE and exposes compiler diagnostics", async ({
    page,
    signedInUser,
    baseURLValue,
  }) => {
    await submitSourceFromUi(page, baseURLValue, HELLO_TOJ_CE);
    await expectChallengeState(page, CHALLENGE_STATE.compileError);
    const compilerMessage = page.locator("#challengeTotalResultMessage");
    await expect(compilerMessage).not.toBeEmpty();
    await expect(compilerMessage).toContainText(/error/i);
  });

  test("administrator can rejudge a completed accepted challenge", async ({
    page,
    adminApi,
    signedInUser,
    baseURLValue,
  }) => {
    const challengeId = await submitSourceFromUi(page, baseURLValue, HELLO_TOJ_AC);
    await expectChallengeState(page, CHALLENGE_STATE.accepted);

    const response = await adminApi.post(appUrl(baseURLValue, "/be/submit"), {
      form: { reqtype: "rechal", chal_id: String(challengeId) },
    });
    await assertApiSuccess(response, `rejudge challenge ${challengeId}`);

    await reloadLoaded(page);
    await expectChallengeState(page, CHALLENGE_STATE.accepted);
    await expect(page.locator("#testdatas td.state")).toHaveClass(/state-1/);
  });

  test(
    "Contest AC updates challenge, problem score and scoreboard",
    { tag: "@contest" },
    async ({ page, adminApi, signedInUser, baseURLValue }) => {
      await gotoLoaded(page, baseURLValue, "/info/");
      const accountId = await page.evaluate(
        () => (window as typeof window & { index: { acct_id: number } }).index.acct_id,
      );
      const contest = await createContest(adminApi, baseURLValue, {
        prefix: "judge-score",
        start: dateFromNow({ hours: -1 }),
        end: dateFromNow({ hours: 2 }),
        regMode: 0,
        contestMode: 0,
        publicScoreboard: true,
      });
      await addContestMember(
        adminApi,
        baseURLValue,
        contest.contestId,
        accountId,
      );
      await addJudgeProblemToContest(
        adminApi,
        baseURLValue,
        contest.contestId,
        "1",
      );

      const challengeId = await submitSourceFromUi(
        page,
        baseURLValue,
        HELLO_TOJ_AC,
        { contestId: contest.contestId },
      );
      await expectChallengeState(page, CHALLENGE_STATE.accepted);

      await expect
        .poll(
          async () => {
            return readContestProblemScore(
              page.request,
              baseURLValue,
              contest.contestId,
              accountId,
            );
          },
          {
            message: "Contest score cache did not reflect the accepted challenge",
            timeout: 30_000,
            intervals: [250, 500, 1_000, 2_000],
          },
        )
        .toMatchObject({
          challengeId,
          problemScore: 100,
          totalScore: 100,
        });

      await gotoLoaded(
        page,
        baseURLValue,
        `/contests/${contest.contestId}/proset/`,
      );
      const problemRow = page.locator("#prolist tbody tr").filter({
        has: page.locator(`a[href*="/pro/${JUDGE_PROBLEM_ID}/"]`),
      });
      await expect(problemRow.locator(".state-1")).toHaveText("Accepted");
      await expect(problemRow.locator("td.score")).toHaveText("100");

      const scoreboardResponse = page.waitForResponse(
        (response) =>
          response.url().endsWith(`/be/contests/${contest.contestId}/scoreboard`) &&
          response.request().method() === "POST",
      );
      await gotoLoaded(
        page,
        baseURLValue,
        `/contests/${contest.contestId}/scoreboard/`,
      );
      expect((await responseJson(await scoreboardResponse)).status).toBe("S");
      const userRow = page.locator("#scoreboard tbody tr").filter({
        hasText: signedInUser.name,
      });
      await expect(userRow).toHaveCount(1);
      await expect(
        userRow.locator(`a[href$="/chal/${challengeId}/"]`),
      ).toHaveText("100");
      await expect(userRow.locator("td").last()).toContainText("100");
    },
  );
});
