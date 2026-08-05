# TOJ fuzz and resilience tests

These tests generate adversarial input instead of relying only on hand-written
examples.

## Property fuzz smoke tests

The ci profile is deterministic and safe to run on every push and pull request.
It requires no database, Redis, Docker, or privileged judge container.

Install and run:

    poetry run python -m pip install -r src/tests/fuzz/requirements.txt
    poetry run bash src/tests/fuzz/run-smoke.sh

For a deeper local run:

    HYPOTHESIS_PROFILE=nightly poetry run bash src/tests/fuzz/run-smoke.sh

The nightly profile runs 5,000 generated examples per property. Hypothesis saves
minimized regression examples under src/.hypothesis when a test fails.

The smoke suite covers bounded numeric parsing, filesystem containment, Batch
judge configuration round trips, malformed Judge protocol messages,
ChalStateCallback privacy, and concurrent duplicate submissions. Service-level
load and fault tests live under src/tests/stress because they have different
runtime, authorization, and isolation requirements.
