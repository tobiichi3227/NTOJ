import { test, expect } from "../src/fixtures";
import { gotoLoaded } from "../src/helpers";
import {
  CHALLENGE_STATE,
  HELLO_TOJ_AC,
  JUDGE_PROBLEM_ID,
  expectChallengeState,
  prepareJudgeProblem,
  submitSourceFromUi,
} from "../src/judge";

test.describe("public rankings", { tag: "@judge" }, () => {
  test.describe.configure({ timeout: 120_000 });

  test.beforeEach(async ({ adminApi, baseURLValue }) => {
    await prepareJudgeProblem(adminApi, baseURLValue);
  });

  test("a non-Contest AC appears in problem and user rankings", async ({
    page,
    signedInUser,
    baseURLValue,
  }) => {
    const challengeId = await submitSourceFromUi(page, baseURLValue, HELLO_TOJ_AC);
    await expectChallengeState(page, CHALLENGE_STATE.accepted);

    await gotoLoaded(
      page,
      baseURLValue,
      `/rank/${JUDGE_PROBLEM_ID}/?pagenum=1000`,
    );
    await expect(page.getByRole("heading", { name: `RankList of ${JUDGE_PROBLEM_ID}` }))
      .toBeVisible();
    const problemRankRow = page.locator("tbody tr").filter({
      has: page.getByRole("link", { name: signedInUser.name, exact: true }),
    });
    await expect(problemRankRow).toHaveCount(1);
    await expect(
      problemRankRow.getByRole("link", { name: String(challengeId), exact: true }),
    ).toBeVisible();
    await expect(problemRankRow.locator("td").nth(4)).toHaveText("100");

    await gotoLoaded(page, baseURLValue, "/users/?pagenum=1000");
    const userRankRow = page.locator("tbody tr").filter({
      has: page.getByRole("link", { name: signedInUser.name, exact: true }),
    });
    await expect(userRankRow).toHaveCount(1);
    await expect(userRankRow.locator("td").nth(4)).toHaveText("1");
    await expect(userRankRow.locator("td").nth(5)).toContainText("100.00%");
    await expect(userRankRow.locator("td").nth(5)).toContainText("1 / 1");
  });
});
