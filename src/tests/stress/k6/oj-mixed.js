import http from "k6/http";
import exec from "k6/execution";
import { check, sleep } from "k6";
import { Counter, Rate } from "k6/metrics";

const baseUrl = (__ENV.BASE_URL || "").replace(/\/+$/, "");
const adminEmail = __ENV.STRESS_ADMIN_EMAIL || "";
const adminPassword = __ENV.STRESS_ADMIN_PASSWORD || "";
const problemId = Number(__ENV.PROBLEM_ID || 1);
const duration = __ENV.DURATION || "60s";
const normalUserVus = positiveInteger(__ENV.NORMAL_USER_VUS, 20);
const normalSubmissionsPerUser = positiveInteger(
  __ENV.NORMAL_SUBMISSIONS_PER_USER,
  1,
);
const contestUserVus = positiveInteger(__ENV.CONTEST_USER_VUS, 10);
const contestCount = positiveInteger(__ENV.CONTEST_COUNT, 3);
const rejudgeRate = positiveInteger(__ENV.REJUDGE_RATE, 1);
const scoreboardRate = positiveInteger(__ENV.SCOREBOARD_RATE, 3);
const rejudgeTargetCount = positiveInteger(__ENV.REJUDGE_TARGET_COUNT, 10);
const scoreboardMaxVus = Math.max(
  positiveInteger(__ENV.SCOREBOARD_MAX_VUS, scoreboardRate * 4),
  scoreboardRate,
  10,
);
const totalVuSlots = normalUserVus + contestUserVus + 1 + scoreboardMaxVus;
const contestCooldownSeconds = positiveInteger(
  __ENV.CONTEST_COOLDOWN_SECONDS,
  1,
);
const contestUserSleep = Number(
  __ENV.CONTEST_USER_SLEEP || contestCooldownSeconds + 0.15,
);
const normalUserSleep = Number(__ENV.NORMAL_USER_SLEEP || 31);

const loginFailures = new Rate("login_failures");
const normalSubmissionFailures = new Rate("normal_submission_failures");
const contestRegistrationFailures = new Rate("contest_registration_failures");
const contestSubmissionFailures = new Rate("contest_submission_failures");
const rejudgeFailures = new Rate("rejudge_failures");
const scoreboardFailures = new Rate("scoreboard_failures");
const applicationErrors = new Counter("application_errors");

let activeIdentity = "";
let registeredContestId = 0;
let loggedFailures = 0;

function positiveInteger(raw, fallback) {
  const parsed = Number(raw || fallback);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

const scenarios = {
  normal_submit: {
    executor: "per-vu-iterations",
    exec: "normalSubmit",
    vus: normalUserVus,
    iterations: normalSubmissionsPerUser,
    startTime: __ENV.WORKLOAD_START_TIME || "5s",
    maxDuration: __ENV.MAX_DURATION || "10m",
    gracefulStop: "30s",
  },
  rejudge: {
    executor: "constant-vus",
    exec: "rejudge",
    vus: 1,
    duration,
    startTime: __ENV.REJUDGE_START_TIME || "10s",
    gracefulStop: "30s",
  },
  scoreboard_read: {
    executor: "constant-arrival-rate",
    exec: "scoreboardRead",
    rate: scoreboardRate,
    timeUnit: "1s",
    duration,
    startTime: __ENV.WORKLOAD_START_TIME || "5s",
    preAllocatedVUs: scoreboardMaxVus,
    maxVUs: scoreboardMaxVus,
    gracefulStop: "10s",
  },
};

for (let contestIndex = 0; contestIndex < contestCount; contestIndex += 1) {
  const vus =
    Math.floor(contestUserVus / contestCount) +
    (contestIndex < contestUserVus % contestCount ? 1 : 0);
  if (vus === 0) {
    continue;
  }
  scenarios["contest_submit_" + contestIndex] = {
    executor: "constant-vus",
    exec: "contestSubmit",
    vus,
    duration,
    startTime: __ENV.WORKLOAD_START_TIME || "5s",
    gracefulStop: "30s",
    env: { CONTEST_INDEX: String(contestIndex) },
  };
}

export const options = {
  noCookiesReset: true,
  // Write-heavy TOJ endpoints currently leave extra HTTP/1.1 responses on
  // reused connections. Isolate response framing while retaining cookies.
  noConnectionReuse: true,
  setupTimeout: __ENV.SETUP_TIMEOUT || "5m",
  scenarios,
  thresholds: {
    checks: ["rate>0.99"],
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<2000", "p(99)<5000"],
    dropped_iterations: ["count==0"],
    login_failures: ["rate<0.01"],
    normal_submission_failures: ["rate<0.01"],
    contest_registration_failures: ["rate<0.01"],
    contest_submission_failures: ["rate<0.01"],
    rejudge_failures: ["rate<0.01"],
    scoreboard_failures: ["rate<0.01"],
  },
};

function parseJson(response) {
  try {
    return response.json();
  } catch (_) {
    return {};
  }
}

function succeeded(response, payload) {
  return response.status === 200 && payload.status === "S";
}

function requireSuccess(response, operation) {
  const payload = parseJson(response);
  if (!succeeded(response, payload)) {
    exec.test.abort(
      operation +
        " failed: HTTP " +
        response.status +
        " payload=" +
        JSON.stringify(payload),
    );
  }
  return payload;
}

function recordResult(metric, operation, response, payload) {
  const ok = succeeded(response, payload);
  metric.add(!ok);
  if (!ok) {
    const status = String(payload.status || "invalid-json");
    applicationErrors.add(1, { operation, status });
    if (loggedFailures < 3) {
      console.error(
        operation +
          " failed: HTTP " +
          response.status +
          " payload=" +
          JSON.stringify(payload),
      );
      loggedFailures += 1;
    }
  }
  return ok;
}

function signIn(email, password) {
  if (activeIdentity === email) {
    return true;
  }
  const response = http.post(
    baseUrl + "/be/sign",
    { reqtype: "signin", mail: email, pw: password },
    { tags: { endpoint: "signin" } },
  );
  const payload = parseJson(response);
  const ok = recordResult(loginFailures, "signin", response, payload);
  if (ok) {
    activeIdentity = email;
  }
  return ok;
}

function sourceCode(role) {
  return (
    "// mixed-" +
    role +
    "-vu-" +
    __VU +
    "-iter-" +
    __ITER +
    "-at-" +
    Date.now() +
    "\n#include <iostream>\n" +
    'int main() { std::cout << "Hello, TOJ!\\n"; return 0; }\n'
  );
}

function setupAdminSignIn() {
  return requireSuccess(
    http.post(baseUrl + "/be/sign", {
      reqtype: "signin",
      mail: adminEmail,
      pw: adminPassword,
    }),
    "setup admin signin",
  );
}

function setupSignOut() {
  requireSuccess(
    http.post(baseUrl + "/be/sign", { reqtype: "signout" }),
    "setup signout",
  );
}

function createContest(runId, index) {
  const name = "stress-" + runId + "-contest-" + index;
  const created = requireSuccess(
    http.post(baseUrl + "/be/contests/manage/add", {
      reqtype: "add",
      name,
    }),
    "create contest " + index,
  );
  const contestId = Number(created.data);
  const now = Date.now();
  requireSuccess(
    http.post(baseUrl + "/be/contests/" + contestId + "/manage/general", {
      reqtype: "update",
      name,
      contest_mode: "1",
      contest_start: new Date(now - 5 * 60 * 1000).toISOString(),
      contest_end: new Date(now + 2 * 60 * 60 * 1000).toISOString(),
      reg_mode: "1",
      reg_end: new Date(now + 2 * 60 * 60 * 1000).toISOString(),
      "allow_compilers[]": "3",
      is_public_scoreboard: "true",
      allow_view_other_page: "false",
      hide_admin: "true",
      submission_cd_time: String(contestCooldownSeconds),
      freeze_scoreboard_period: "0",
      penalty_value: "20",
      enable_system_test: "false",
    }),
    "configure contest " + contestId,
  );
  requireSuccess(
    http.post(baseUrl + "/be/contests/" + contestId + "/manage/pro", {
      reqtype: "add",
      pro_id: String(problemId),
      score_type: "1",
    }),
    "add problem to contest " + contestId,
  );
  return contestId;
}

function createRejudgeTarget(runId, index) {
  const response = http.post(baseUrl + "/be/submit", {
    reqtype: "submit",
    pro_id: String(problemId),
    compiler_type: "3",
    code:
      "// rejudge-target-" +
      runId +
      "-" +
      index +
      "\n#include <iostream>\n" +
      'int main() { std::cout << "Hello, TOJ!\\n"; return 0; }\n',
  });
  const payload = requireSuccess(response, "create rejudge target " + index);
  return Number(payload.data);
}

function createUser(runId, index, password) {
  const identity = "s-" + runId.slice(-10) + "-u" + index;
  requireSuccess(
    http.post(baseUrl + "/be/sign", {
      reqtype: "signup",
      name: identity,
      mail: identity + "@example.test",
      pw: password,
    }),
    "create user " + index,
  );
  setupSignOut();
  return { email: identity + "@example.test", password };
}

export function setup() {
  if (__ENV.CONFIRM_JUDGE_STRESS !== "true") {
    exec.test.abort("Mixed OJ stress requires CONFIRM_JUDGE_STRESS=true");
  }
  if (!baseUrl || !adminEmail || !adminPassword) {
    exec.test.abort("BASE_URL and stress admin credentials are required");
  }
  if (!Number.isSafeInteger(problemId) || problemId <= 0) {
    exec.test.abort("PROBLEM_ID must be a positive integer");
  }
  if (!Number.isFinite(contestUserSleep) || contestUserSleep < contestCooldownSeconds) {
    exec.test.abort("CONTEST_USER_SLEEP must be at least CONTEST_COOLDOWN_SECONDS");
  }

  const runId = String(__ENV.STRESS_RUN_ID || Date.now()).replace(/[^0-9A-Za-z]/g, "");
  const userPassword = __ENV.STRESS_USER_PASSWORD || "Stress-password-123";

  setupAdminSignIn();
  requireSuccess(
    http.post(baseUrl + "/be/manage/pro/update", {
      reqtype: "updategeneral",
      pro_id: String(problemId),
      name: "HelloTOJ",
      tags: "stress,judge",
      status: "0",
      allow_submit: "true",
    }),
    "expose stress problem",
  );

  const judgeProbe = http.post(baseUrl + "/be/submit", {
    reqtype: "submit",
    pro_id: String(problemId),
    compiler_type: "3",
    code: "",
  });
  const judgeProbePayload = parseJson(judgeProbe);
  if (judgeProbe.status !== 200 || judgeProbePayload.status !== "Eempty") {
    exec.test.abort("Judge is not ready: " + JSON.stringify(judgeProbePayload));
  }

  const contestIds = [];
  for (let index = 0; index < contestCount; index += 1) {
    contestIds.push(createContest(runId, index));
  }

  const rejudgeIds = [];
  for (let index = 0; index < rejudgeTargetCount; index += 1) {
    rejudgeIds.push(createRejudgeTarget(runId, index));
  }
  setupSignOut();

  const users = [];
  for (let index = 0; index < totalVuSlots; index += 1) {
    users.push(createUser(runId, index, userPassword));
  }

  return {
    runId,
    contestIds,
    rejudgeIds,
    usersByVu: users,
  };
}

function assignedUser(usersByVu) {
  const user = usersByVu[exec.vu.idInTest - 1];
  if (!user) {
    exec.test.abort("No dedicated user for VU " + exec.vu.idInTest);
  }
  return user;
}

export function normalSubmit(data) {
  const user = assignedUser(data.usersByVu);
  if (!signIn(user.email, user.password)) {
    sleep(1);
    return;
  }
  const response = http.post(
    baseUrl + "/be/submit",
    {
      reqtype: "submit",
      pro_id: String(problemId),
      compiler_type: "3",
      code: sourceCode("normal"),
    },
    { tags: { endpoint: "normal-submit" } },
  );
  const payload = parseJson(response);
  const ok = recordResult(
    normalSubmissionFailures,
    "normal-submit",
    response,
    payload,
  );
  check(response, {
    "normal submission is accepted": () => ok,
    "normal challenge id is returned": () => Number(payload.data) > 0,
  });
  if (normalSubmissionsPerUser > 1) {
    sleep(normalUserSleep);
  }
}

export function contestSubmit(data) {
  const user = assignedUser(data.usersByVu);
  const contestId = data.contestIds[Number(__ENV.CONTEST_INDEX)];
  if (!signIn(user.email, user.password)) {
    sleep(1);
    return;
  }

  if (registeredContestId !== contestId) {
    const registration = http.post(
      baseUrl + "/be/contests/" + contestId + "/reg",
      { reqtype: "reg" },
      { tags: { endpoint: "contest-register" } },
    );
    const registrationPayload = parseJson(registration);
    const registered = recordResult(
      contestRegistrationFailures,
      "contest-register",
      registration,
      registrationPayload,
    );
    check(registration, { "contest registration succeeds": () => registered });
    if (!registered) {
      sleep(1);
      return;
    }
    registeredContestId = contestId;
  }

  const response = http.post(
    baseUrl + "/be/contests/" + contestId + "/submit",
    {
      reqtype: "submit",
      pro_id: String(problemId),
      compiler_type: "3",
      code: sourceCode("contest-" + contestId),
    },
    { tags: { endpoint: "contest-submit", contest_id: String(contestId) } },
  );
  const payload = parseJson(response);
  const ok = recordResult(
    contestSubmissionFailures,
    "contest-submit",
    response,
    payload,
  );
  check(response, {
    "contest submission is accepted": () => ok,
    "contest challenge id is returned": () => Number(payload.data) > 0,
  });
  sleep(contestUserSleep);
}

export function rejudge(data) {
  if (!signIn(adminEmail, adminPassword)) {
    sleep(1);
    return;
  }
  const challengeId = data.rejudgeIds[__ITER % data.rejudgeIds.length];
  const response = http.post(
    baseUrl + "/be/submit",
    { reqtype: "rechal", chal_id: String(challengeId) },
    { tags: { endpoint: "rejudge" } },
  );
  const payload = parseJson(response);
  const ok = recordResult(rejudgeFailures, "rejudge", response, payload);
  check(response, { "rejudge is accepted": () => ok });
  sleep(1 / rejudgeRate);
}

export function scoreboardRead(data) {
  const contestId = data.contestIds[__ITER % data.contestIds.length];
  const response = http.post(
    baseUrl + "/be/contests/" + contestId + "/scoreboard",
    null,
    { tags: { endpoint: "scoreboard", contest_id: String(contestId) } },
  );
  const payload = parseJson(response);
  const ok = recordResult(
    scoreboardFailures,
    "scoreboard",
    response,
    payload,
  );
  check(response, { "scoreboard remains available": () => ok });
}
