# Archived Python Playwright suite

This directory preserves the complete pytest-playwright implementation that
predated the Node.js Playwright Test suite in `../node/`.

The Node suite is the primary maintained runner. Keep this Python suite for
coverage comparison, regression archaeology, and environments that explicitly
require pytest.

## Install

From the repository root:

```bash
poetry run pip install -r src/tests/e2e/python/requirements.txt
poetry run playwright install chromium
```

## Collect and run

```bash
poetry run pytest \
  -c src/tests/e2e/python/pytest.ini \
  src/tests/e2e/python \
  --collect-only

poetry run pytest \
  -c src/tests/e2e/python/pytest.ini \
  src/tests/e2e/python \
  -m "not judge"
```

The suite targets `http://127.0.0.1:5500` by default. Use
`NTOJ_E2E_BASE_URL`, `NTOJ_E2E_ADMIN_EMAIL`, and
`NTOJ_E2E_ADMIN_PASSWORD` to override its environment.

## Python UI tools

Run Playwright Inspector:

```bash
poetry run python src/tests/e2e/python/e2e_ui.py -m contest
```

Generate and serve the archived Python dashboard:

```bash
poetry run python src/tests/e2e/python/run_test_ui.py -m contest
```

Dashboard and failure artifacts remain inside this directory so the Python and
Node runners do not share generated output.
