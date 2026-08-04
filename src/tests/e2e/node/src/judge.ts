import { APIRequestContext, Page, expect } from "@playwright/test";
import {
  appUrl,
  assertApiSuccess,
  gotoLoaded,
  responseJson,
  waitForContainer,
} from "./helpers";

export const JUDGE_PROBLEM_ID = Number(process.env.NTOJ_E2E_PROBLEM_ID ?? "1");
export const GPP_COMPILER = "3";
export const PYTHON3_COMPILER = "6";

export const HELLO_TOJ_AC = `#include <iostream>
int main() {
  std::cout << "Hello, TOJ!\\n";
  return 0;
}
`;

export const HELLO_TOJ_WA = `#include <iostream>
int main() {
  std::cout << "Wrong answer\\n";
  return 0;
}
`;

export const HELLO_TOJ_CE = `#include <iostream>
int main( {
  return 0;
}
`;

type ChallengeState = {
  className: string;
  longName: string;
  score: string;
};

export type SubmitSourceOptions = {
  contestId?: number;
  compiler?: string;
  compilerLabel?: string;
};

export type ContestProblemScore = {
  challengeId: number;
  failCount: number;
  problemScore: number;
  totalScore: number;
};

export const CHALLENGE_STATE = {
  accepted: {
    className: "state-1",
    longName: "Accepted",
    score: "100",
  },
  wrongAnswer: {
    className: "state-3",
    longName: "Wrong Answer",
    score: "0",
  },
  runtimeError: {
    className: "state-4",
    longName: "Runtime Error",
    score: "0",
  },
  runtimeSignal: {
    className: "state-5",
    longName: "Runtime Error (Killed by signal)",
    score: "0",
  },
  timeLimit: {
    className: "state-6",
    longName: "Time Limit Exceed",
    score: "0",
  },
  compileError: {
    className: "state-9",
    longName: "Compile Error",
    score: "0",
  },
} satisfies Record<string, ChallengeState>;

export async function exposeSeedJudgeProblem(
  adminApi: APIRequestContext,
  baseURL: string,
): Promise<void> {
  expect(Number.isSafeInteger(JUDGE_PROBLEM_ID) && JUDGE_PROBLEM_ID > 0).toBeTruthy();
  const response = await adminApi.post(appUrl(baseURL, "/be/manage/pro/update"), {
    form: {
      reqtype: "updategeneral",
      pro_id: String(JUDGE_PROBLEM_ID),
      name: "HelloTOJ",
      tags: "e2e,judge",
      status: "0",
      allow_submit: "true",
    },
  });
  await assertApiSuccess(response, `expose Judge problem ${JUDGE_PROBLEM_ID}`);
}

export async function waitForJudgeOnline(
  adminApi: APIRequestContext,
  baseURL: string,
): Promise<void> {
  await expect
    .poll(
      async () => {
        const response = await adminApi.post(appUrl(baseURL, "/be/submit"), {
          form: {
            reqtype: "submit",
            pro_id: String(JUDGE_PROBLEM_ID),
            code: "",
            compiler_type: GPP_COMPILER,
          },
        });
        const payload = await responseJson(response);
        return payload.status;
      },
      {
        message:
          "Judge did not become available. Start the privileged Compose Judge profile before running @judge tests.",
        timeout: 60_000,
        intervals: [500, 1_000, 2_000, 5_000],
      },
    )
    .toBe("Eempty");
}

export async function prepareJudgeProblem(
  adminApi: APIRequestContext,
  baseURL: string,
): Promise<void> {
  await exposeSeedJudgeProblem(adminApi, baseURL);
  await waitForJudgeOnline(adminApi, baseURL);
}

export async function addJudgeProblemToContest(
  adminApi: APIRequestContext,
  baseURL: string,
  contestId: number,
  scoreType?: string,
): Promise<void> {
  const response = await adminApi.post(
    appUrl(baseURL, "/be/contests/" + contestId + "/manage/pro"),
    {
      form: {
        reqtype: "add",
        pro_id: String(JUDGE_PROBLEM_ID),
        ...(scoreType === undefined ? {} : { score_type: scoreType }),
      },
    },
  );
  await assertApiSuccess(
    response,
    "add problem " + JUDGE_PROBLEM_ID + " to Contest " + contestId,
  );
}

export async function readContestProblemScore(
  api: APIRequestContext,
  baseURL: string,
  contestId: number,
  accountId: number,
): Promise<ContestProblemScore | null> {
  const response = await api.post(
    appUrl(baseURL, "/be/contests/" + contestId + "/scoreboard"),
  );
  const payload = await responseJson(response);
  if (payload.status !== "S" || !Array.isArray(payload.data)) return null;

  const entry = (
    payload.data as Array<{
      acct_id: number;
      total_score: number | string;
      scores: Record<
        string,
        {
          chal_id: number;
          fail_cnt?: number;
          score: number | string;
        }
      >;
    }>
  ).find((candidate) => candidate.acct_id === accountId);
  const problemScore = entry?.scores[String(JUDGE_PROBLEM_ID)];
  if (!entry || !problemScore) return null;

  return {
    challengeId: problemScore.chal_id,
    failCount: problemScore.fail_cnt ?? 0,
    problemScore: Number(problemScore.score),
    totalScore: Number(entry.total_score),
  };
}

export async function submitSourceFromUi(
  page: Page,
  baseURL: string,
  source: string,
  options: SubmitSourceOptions = {},
): Promise<number> {
  const {
    contestId = 0,
    compiler = GPP_COMPILER,
    compilerLabel = "G++",
  } = options;
  const submitPath =
    contestId === 0
      ? `/submit/${JUDGE_PROBLEM_ID}/`
      : `/contests/${contestId}/submit/${JUDGE_PROBLEM_ID}/`;
  await gotoLoaded(page, baseURL, submitPath);
  await expect(page.locator("#submit")).toBeVisible();
  await expect(page.locator(`#compilerList option[value="${compiler}"]`)).toContainText(
    compilerLabel,
  );
  await page.locator("#compilerList").selectOption(compiler);
  await page.locator("#codeArea").fill(source);

  const endpoint =
    contestId === 0 ? "/be/submit" : `/be/contests/${contestId}/submit`;
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith(endpoint) && response.request().method() === "POST",
  );
  await page.locator("#submit button.submit").click();
  const payload = await responseJson(await responsePromise);
  expect(payload.status, `submission failed: ${JSON.stringify(payload)}`).toBe("S");

  const challengeId = Number(payload.data);
  expect(Number.isSafeInteger(challengeId) && challengeId > 0).toBeTruthy();
  const challengePath =
    contestId === 0
      ? `/chal/${challengeId}/`
      : `/contests/${contestId}/chal/${challengeId}/`;
  await page.waitForURL(appUrl(baseURL, challengePath));
  await waitForContainer(page);
  return challengeId;
}

export async function expectChallengeState(
  page: Page,
  state: ChallengeState,
): Promise<void> {
  const totalState = page.locator("#total td.state");
  await expect(totalState).not.toHaveClass(
    /(?:^|\s)state-(?:100|101)(?:\s|$)/,
    { timeout: 90_000 },
  );
  await expect(totalState).toHaveClass(new RegExp(`(?:^|\\s)${state.className}(?:\\s|$)`), {
    timeout: 5_000,
  });
  await expect(totalState).toHaveText(state.longName);
  await expect(page.locator("#total td.score")).toHaveText(state.score);
}
