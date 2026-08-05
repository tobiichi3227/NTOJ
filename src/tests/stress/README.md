# TOJ stress and fault tests

These profiles are intentionally separate from push and pull-request checks.

Public read load:

    BASE_URL=http://host.docker.internal:5500 \
      src/tests/stress/run-k6.sh public-read

Remote targets require CONFIRM_ISOLATED=true. The default profile uses 5 virtual
users for 30 seconds. Override VUS and DURATION to increase load.

Judge submission load is destructive: it creates challenge records and dispatches
real privileged Judge jobs. Use only a disposable full-deployment fixture with a
seed problem, and provide the admin credentials through environment variables:

    CONFIRM_ISOLATED=true \
    CONFIRM_JUDGE_STRESS=true \
    BASE_URL=http://host.docker.internal:5500 \
    STRESS_ADMIN_EMAIL=admin@example.test \
    STRESS_ADMIN_PASSWORD=secret \
    PROBLEM_ID=1 \
    RATE=1 \
    DURATION=30s \
      src/tests/stress/run-k6.sh judge-submit

`judge-submit` deliberately uses one VU by default because TOJ invalidates an
account's older session when that same account signs in again. To create an exact
number of challenges, set `TOTAL_SUBMISSIONS`; keep `VUS=1`.

Mixed OJ load creates independent users and active contests before running four
workloads together: normal user submissions, submissions across multiple ACM
contests, administrator rejudge requests, and public scoreboard reads. Every
submission VU owns a different account so sessions do not invalidate each other:

    CONFIRM_ISOLATED=true 
    CONFIRM_JUDGE_STRESS=true 
    BASE_URL=http://host.docker.internal:5500 
    STRESS_ADMIN_EMAIL=admin@example.test 
    STRESS_ADMIN_PASSWORD=secret 
    PROBLEM_ID=1 
    NORMAL_USER_VUS=30 
    CONTEST_USER_VUS=12 
    CONTEST_COUNT=3 
    REJUDGE_TARGET_COUNT=12 
    REJUDGE_RATE=1 
    SCOREBOARD_RATE=5 
    SCOREBOARD_MAX_VUS=20 
    DURATION=2m 
      src/tests/stress/run-k6.sh oj-mixed

Contest submissions use a one-second cooldown and unique source text. Normal
users submit once by default because the non-Contest application cooldown is 30
seconds. Set `NORMAL_SUBMISSIONS_PER_USER` above one only together with a
`NORMAL_USER_SLEEP` of at least 30 seconds.

`REJUDGE_RATE` controls the maximum sequential rejudge pace for one stable admin
session. `SCOREBOARD_MAX_VUS` defaults to four times `SCOREBOARD_RATE` (at least
10) so slow scoreboard requests are recorded as latency instead of dropped work.
Set a unique `STRESS_RUN_ID` for each run; the runner includes its sanitized value
in the summary filename so overlapping runs cannot overwrite each other's report.

The GitHub stress-tests workflow exposes all profiles behind a required manual
isolation confirmation. Credentials come from STRESS_ADMIN_EMAIL and
STRESS_ADMIN_PASSWORD repository secrets.

During a local public-read run, inject a short dependency outage from another
terminal:

    CONFIRM_ISOLATED=true \
      src/tests/stress/fault/run-compose-fault.sh judge 10

The helper only accepts judge, cache, or db and automatically unpauses the
service. Its outage duration is capped at 30 seconds.
