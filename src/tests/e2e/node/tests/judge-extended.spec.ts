import { test, expect } from "../src/fixtures";
import {
  addContestMember,
  appUrl,
  createContest,
  dateFromNow,
  gotoLoaded,
  responseJson,
} from "../src/helpers";
import {
  addJudgeProblemToContest,
  CHALLENGE_STATE,
  GPP_COMPILER,
  HELLO_TOJ_AC,
  HELLO_TOJ_WA,
  JUDGE_PROBLEM_ID,
  PYTHON3_COMPILER,
  expectChallengeState,
  prepareJudgeProblem,
  readContestProblemScore,
  submitSourceFromUi,
} from "../src/judge";

const HELLO_TOJ_PYTHON_AC = 'print("Hello, TOJ!")\n';
const RUNTIME_ERROR = `int main() {
  return -1;
}
`;
const RUNTIME_SIGNAL = `#include <csignal>
int main() {
  std::raise(SIGSEGV);
}
`;
const TIME_LIMIT = `int main() {
  while (true) {}
}
`;

test.describe("Judge extended verdicts and policy", { tag: "@judge" }, () => {
  test.describe.configure({ timeout: 120_000 });

  test.beforeEach(async ({ adminApi, baseURLValue }) => {
    await prepareJudgeProblem(adminApi, baseURLValue);
  });

  test("Python 3 solution reaches AC and preserves compiler metadata", async ({
    page,
    signedInUser,
    baseURLValue,
  }) => {
    await submitSourceFromUi(
      page,
      baseURLValue,
      HELLO_TOJ_PYTHON_AC,
      { compiler: PYTHON3_COMPILER, compilerLabel: "CPython" },
    );
    await expectChallengeState(page, CHALLENGE_STATE.accepted);
    await expect(page.locator("#info")).toContainText("CPython 3.13.5");
    await expect(page.locator("#code code")).toContainText("Hello, TOJ!");
  });

  const verdictCases = [
    {
      title: "non-zero exit reaches RE",
      source: RUNTIME_ERROR,
      state: CHALLENGE_STATE.runtimeError,
    },
    {
      title: "fatal signal reaches RESIG",
      source: RUNTIME_SIGNAL,
      state: CHALLENGE_STATE.runtimeSignal,
      expectedFailure:
        "Judge Rewrite currently treats SIGSEGV as normal execution and returns WA; docs/system.md requires RESIG.",
    },
    {
      title: "infinite loop reaches TLE",
      source: TIME_LIMIT,
      state: CHALLENGE_STATE.timeLimit,
    },
  ];

  for (const verdictCase of verdictCases) {
    test(verdictCase.title, async ({ page, signedInUser, baseURLValue }) => {
      test.fail(Boolean(verdictCase.expectedFailure), verdictCase.expectedFailure);
      await submitSourceFromUi(page, baseURLValue, verdictCase.source);
      await expectChallengeState(page, verdictCase.state);
      await expect(page.locator("#testdatas td.state")).toHaveClass(
        new RegExp(verdictCase.state.className),
      );
    });
  }

  test("submission validation rejects empty, oversized and invalid compiler input", async ({
    page,
    signedInUser,
    baseURLValue,
  }) => {
    await gotoLoaded(page, baseURLValue, `/submit/${JUDGE_PROBLEM_ID}/`);
    await page.locator("#codeArea").fill("   ");
    await page.locator("#submit button.submit").click();
    await expect(page.locator("#indexNotifyDialog .modal-body")).toHaveText(
      "Code cannot be empty",
    );

    let response = await page.request.post(appUrl(baseURLValue, "/be/submit"), {
      form: {
        reqtype: "submit",
        pro_id: String(JUDGE_PROBLEM_ID),
        code: "x".repeat(16_385),
        compiler_type: GPP_COMPILER,
      },
    });
    let payload = await responseJson(response);
    expect(payload).toMatchObject({
      status: "Ecodemax",
      data: "Submitted code too long",
    });

    response = await page.request.post(appUrl(baseURLValue, "/be/submit"), {
      form: {
        reqtype: "submit",
        pro_id: String(JUDGE_PROBLEM_ID),
        code: HELLO_TOJ_AC,
        compiler_type: "999",
      },
    });
    payload = await responseJson(response);
    expect(payload).toMatchObject({
      status: "Ecomp",
      data: "The compiler is not allowed",
    });
  });

  test("public challenge hides source code from a non-owner", async ({
    page,
    signedInUser,
    baseURLValue,
    newTrackedContext,
  }) => {
    const challengeId = await submitSourceFromUi(page, baseURLValue, HELLO_TOJ_AC);
    await expectChallengeState(page, CHALLENGE_STATE.accepted);

    const guestContext = await newTrackedContext();
    const denied = await guestContext.request.post(appUrl(baseURLValue, "/be/code"), {
      form: { chal_id: String(challengeId) },
    });
    expect(await responseJson(denied)).toMatchObject({
      status: "Eacces",
      data: "Permission denied",
    });

    const guestPage = await guestContext.newPage();
    await gotoLoaded(guestPage, baseURLValue, `/chal/${challengeId}/`);
    await expectChallengeState(guestPage, CHALLENGE_STATE.accepted);
    await expect(guestPage.locator("#code code")).toBeEmpty();
  });

  test(
    "ACM scoreboard counts a WA before AC and applies penalty",
    { tag: "@contest" },
    async ({ page, adminApi, signedInUser, baseURLValue }) => {
      await gotoLoaded(page, baseURLValue, "/info/");
      const accountId = await page.evaluate(
        () => (window as typeof window & { index: { acct_id: number } }).index.acct_id,
      );
      const contestStart = dateFromNow({ hours: -1 });
      const contest = await createContest(adminApi, baseURLValue, {
        prefix: "judge-acm-penalty",
        start: contestStart,
        end: dateFromNow({ hours: 2 }),
        regMode: 0,
        contestMode: 1,
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
      );

      await submitSourceFromUi(
        page,
        baseURLValue,
        HELLO_TOJ_WA,
        { contestId: contest.contestId },
      );
      await expectChallengeState(page, CHALLENGE_STATE.wrongAnswer);
      await page.waitForTimeout(1_100);

      const acceptedChallengeId = await submitSourceFromUi(
        page,
        baseURLValue,
        HELLO_TOJ_AC,
        { contestId: contest.contestId },
      );
      await expectChallengeState(page, CHALLENGE_STATE.accepted);

      let score = await readContestProblemScore(
        page.request,
        baseURLValue,
        contest.contestId,
        accountId,
      );
      await expect
        .poll(
          async () => {
            score = await readContestProblemScore(
              page.request,
              baseURLValue,
              contest.contestId,
              accountId,
            );
            return score;
          },
          {
            message: "ACM score did not include the WA before AC",
            timeout: 30_000,
            intervals: [250, 500, 1_000, 2_000],
          },
        )
        .not.toBeNull();

      expect(score).not.toBeNull();
      const finalScore = score!;
      expect(finalScore.challengeId).toBe(acceptedChallengeId);
      expect(finalScore.failCount).toBe(1);
      expect(finalScore.problemScore).toBe(finalScore.totalScore);
      const elapsedMinutes = Math.floor(
        (Date.now() - contestStart.getTime()) / 60_000,
      );
      expect(finalScore.totalScore).toBeGreaterThanOrEqual(elapsedMinutes + 20);
      expect(finalScore.totalScore).toBeLessThanOrEqual(elapsedMinutes + 21);

      await gotoLoaded(
        page,
        baseURLValue,
        `/contests/${contest.contestId}/scoreboard/`,
      );
      const userRow = page.locator("#scoreboard tbody tr").filter({
        hasText: signedInUser.name,
      });
      await expect(userRow).toHaveCount(1);
      await expect(userRow.getByText("2 tries", { exact: true })).toBeVisible();
      await expect(
        userRow.locator(`a[href$="/chal/${acceptedChallengeId}/"]`),
      ).toHaveCount(1);
      await expect(userRow.locator("td").last()).toContainText(
        String(finalScore.totalScore),
      );
    },
  );
});
