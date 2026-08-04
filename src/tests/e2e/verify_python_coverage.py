#!/usr/bin/env python3

import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path


def verify_totals(totals: dict, threshold: Decimal) -> list[str]:
    checks = (
        ("statements", "percent_statements_covered", "missing_lines"),
        ("branches", "percent_branches_covered", "missing_branches"),
    )
    failures = []
    for label, percent_key, missing_key in checks:
        percent = Decimal(str(totals[percent_key]))
        missing = int(totals[missing_key])
        print(
            f"Python {label}: {percent:.2f}% (missing: {missing}, required: {threshold:.2f}%)"
        )
        if percent < threshold:
            failures.append(
                f"{label} coverage {percent:.2f}% is below {threshold:.2f}%"
            )
        if threshold == 100 and missing != 0:
            failures.append(
                f"{label} coverage reports {missing} missing item(s) at a 100% gate"
            )
    return failures


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"Usage: {argv[0]} COVERAGE_JSON THRESHOLD", file=sys.stderr)
        return 2

    try:
        threshold = Decimal(argv[2])
    except InvalidOperation:
        print(f"Invalid coverage threshold: {argv[2]}", file=sys.stderr)
        return 2
    if not 0 <= threshold <= 100:
        print(
            f"Coverage threshold must be between 0 and 100: {threshold}",
            file=sys.stderr,
        )
        return 2

    try:
        totals = json.loads(Path(argv[1]).read_text(encoding="utf-8"))["totals"]
        failures = verify_totals(totals, threshold)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"Invalid coverage report {argv[1]}: {exc}", file=sys.stderr)
        return 2

    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
