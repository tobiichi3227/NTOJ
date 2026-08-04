# Contest specification differences

These differences were confirmed while building the Playwright E2E suite against the current implementation.

## Permanent contest category

`docs/contest.md` defines Active, Upcoming, Recent, and Permanent contest categories. `ContestListHandler` creates a `permanent` list but never appends a contest to it, and the contest model has no permanent flag or equivalent rule. The Permanent table is therefore always empty.

The E2E lifecycle test covers the three implemented time-based categories.

## Submission cooldown unit

`docs/contest-manage.md` labels Submit CD Time as milliseconds. The management UI labels the field as seconds, defaults it to 30 for IOI and 1 for ACM, and submission enforcement compares it directly with `time.time()` seconds. The current implementation is consistently seconds.

## Contest creator removal

`docs/contest-manage.md` marks creator deletion protection as not implemented. `ContestManageAcctHandler` now explicitly rejects removal of `contest_creator` with `Cannot remove contest creator`.

## Challenge style options

The specification lists a Subtask State Count challenge style as not implemented. The current `ChallengeResultStyle` enum and management UI expose Full, State Count, Subtask Only, and Total Only; no Subtask State Count value exists.

The E2E problem-management test covers the implemented IOI score-type and Total Only transitions.


## Description escaping

Contest descriptions support Markdown preview and DOMPurify sanitization. However, descriptions are embedded into an inline JavaScript template literal by `markdown_escape`, which currently escapes only backslashes and backticks. A literal `</script>` terminates the script element and prevents the description from rendering.

The passing E2E test verifies event-handler sanitization. The literal closing-tag limitation is also tracked in `KNOWN_ISSUES.md`.
