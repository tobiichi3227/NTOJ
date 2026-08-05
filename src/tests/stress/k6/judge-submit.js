import http from "k6/http";
import exec from "k6/execution";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";

const baseUrl = (__ENV.BASE_URL || "").replace(/\/+$/, "");
const adminEmail = __ENV.STRESS_ADMIN_EMAIL || "";
const adminPassword = __ENV.STRESS_ADMIN_PASSWORD || "";
const problemId = Number(__ENV.PROBLEM_ID || 1);
const exactIterations = Number(__ENV.TOTAL_SUBMISSIONS || 0);
const submissionFailures = new Rate("submission_failures");
let signedIn = false;

const judgeScenario =
  exactIterations > 0
    ? {
        executor: "shared-iterations",
        vus: Number(__ENV.VUS || 1),
        iterations: exactIterations,
        maxDuration: __ENV.MAX_DURATION || "10m",
      }
    : {
        executor: "constant-arrival-rate",
        rate: Number(__ENV.RATE || 1),
        timeUnit: "1s",
        duration: __ENV.DURATION || "30s",
        // A single TOJ account cannot safely back multiple VUs: a new login
        // invalidates that account's previous session. Use oj-mixed for
        // concurrent submissions backed by separate users.
        preAllocatedVUs: Number(__ENV.PRE_ALLOCATED_VUS || 1),
        maxVUs: Number(__ENV.MAX_VUS || 1),
        gracefulStop: "30s",
      };

export const options = {
  // k6 clears a VU's cookie jar between iterations by default. The TOJ
  // session must survive because signedIn is also scoped to the VU.
  noCookiesReset: true,
  scenarios: {
    judge_submit: judgeScenario,
  },
  thresholds: {
    checks: ["rate>0.99"],
    submission_failures: ["rate<0.01"],
    http_req_duration: ["p(95)<2000", "p(99)<5000"],
    dropped_iterations: ["count==0"],
  },
};

function parseJson(response) {
  try {
    return response.json();
  } catch (_) {
    return {};
  }
}

function ensureSignedIn() {
  if (signedIn) {
    return true;
  }

  const response = http.post(
    baseUrl + "/be/sign",
    {
      reqtype: "signin",
      mail: adminEmail,
      pw: adminPassword,
    },
    { tags: { endpoint: "signin" } },
  );
  const payload = parseJson(response);
  signedIn = response.status === 200 && payload.status === "S";
  return signedIn;
}

export function setup() {
  if (__ENV.CONFIRM_JUDGE_STRESS !== "true") {
    exec.test.abort("Judge stress requires CONFIRM_JUDGE_STRESS=true");
  }
  if (!baseUrl || !adminEmail || !adminPassword) {
    exec.test.abort("BASE_URL and stress admin credentials are required");
  }
  if (!Number.isSafeInteger(problemId) || problemId <= 0) {
    exec.test.abort("PROBLEM_ID must be a positive integer");
  }
}

export default function () {
  if (!ensureSignedIn()) {
    submissionFailures.add(true);
    check(null, { "admin sign-in succeeds": () => false });
    sleep(1);
    return;
  }

  const uniqueComment =
    "// k6-vu-" + __VU + "-iter-" + __ITER + "-at-" + Date.now();
  const source =
    uniqueComment +
    "\n#include <iostream>\nint main() { std::cout << \"Hello, TOJ!\\n\"; return 0; }\n";
  const response = http.post(
    baseUrl + "/be/submit",
    {
      reqtype: "submit",
      pro_id: String(problemId),
      compiler_type: "3",
      code: source,
    },
    { tags: { endpoint: "judge-submit" } },
  );
  const payload = parseJson(response);
  const succeeded = response.status === 200 && payload.status === "S";

  submissionFailures.add(!succeeded);
  check(response, {
    "Judge submission is accepted": () => succeeded,
    "challenge id is returned": () => Number(payload.data) > 0,
  });
  sleep(Number(__ENV.REQUEST_SLEEP || 0));
}
