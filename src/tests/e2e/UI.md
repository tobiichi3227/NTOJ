# Playwright Test UI

The suite uses the official Node.js Playwright Test UI.

Start it from the repository root:

```bash
docker compose \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  up -d --build node-tests
```

Then open <http://127.0.0.1:9323>.

After `bash src/tests/e2e/run-coverage.sh`, the combined Python and browser
coverage landing page is available at <http://127.0.0.1:9325>.

## What to try

- Use the left-side triangle to run all 64 tests.
- Search for `@contest` to focus on Contest coverage.
- Click a test title to inspect its source and every browser action.
- After running a test, use the timeline to inspect DOM snapshots before and
  after each click, fill, request, or assertion.
- Toggle the eye icon to watch the live Chromium window.
- Use the locator picker to inspect and refine selectors.

One test is an expected failure: `fatal signal reaches RESIG` demonstrates the
current external Judge signal classification defect. Its red test-step marker
is expected, while the overall run remains successful.

## Completed-run report

Every selected test retains a full trace, an end-of-test PNG screenshot, and a
WebM video. After a run, serve the generated report separately:

```bash
cd src/tests/e2e/node
npx playwright show-report playwright-report --host 127.0.0.1 --port 9324
```

Open <http://127.0.0.1:9324> and click a test to view its screenshot, video,
and Trace Viewer timeline.

The UI listens only on host loopback (`127.0.0.1:9323`). Test data lives in
disposable Docker volumes and can be removed with the cleanup command in
[`DOCKER.md`](DOCKER.md).