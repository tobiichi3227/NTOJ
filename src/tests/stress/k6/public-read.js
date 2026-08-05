import http from "k6/http";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";

const baseUrl = (__ENV.BASE_URL || "http://127.0.0.1:5500").replace(/\/+$/, "");
const paths = (__ENV.READ_PATHS || "/,/be/info,/be/proset,/be/chal,/be/contests,/be/users")
  .split(",")
  .map((path) => path.trim())
  .filter(Boolean);

const serverErrors = new Rate("server_errors");
const unexpectedStatuses = new Rate("unexpected_statuses");

export const options = {
  scenarios: {
    public_read: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 5),
      duration: __ENV.DURATION || "30s",
      gracefulStop: "10s",
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    server_errors: ["rate<0.01"],
    unexpected_statuses: ["rate<0.01"],
    http_req_duration: ["p(95)<1000", "p(99)<2500"],
  },
};

export default function () {
  const path = paths[(__VU + __ITER) % paths.length];
  const response = http.get(baseUrl + path, {
    redirects: 3,
    tags: { endpoint: path },
  });
  const serverError = response.status === 0 || response.status >= 500;
  const unexpected = response.status < 200 || response.status >= 400;

  serverErrors.add(serverError);
  unexpectedStatuses.add(unexpected);
  check(response, {
    "HTTP status is 2xx or 3xx": () => !unexpected,
    "response is not empty": (value) => value.body !== null && value.body.length > 0,
  });

  sleep(Number(__ENV.REQUEST_SLEEP || 0.2));
}
