import contextlib
import importlib.util
import io
import unittest
from decimal import Decimal
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "e2e" / "verify_python_coverage.py"
SPEC = importlib.util.spec_from_file_location("verify_python_coverage", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
verify_python_coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_python_coverage)


class CoverageGateTest(unittest.TestCase):
    def verify(self, totals, threshold):
        with contextlib.redirect_stdout(io.StringIO()):
            return verify_python_coverage.verify_totals(totals, Decimal(threshold))

    def test_accepts_complete_statement_and_branch_coverage(self):
        failures = self.verify(
            {
                "percent_statements_covered": 100,
                "missing_lines": 0,
                "percent_branches_covered": 100,
                "missing_branches": 0,
            },
            "100",
        )
        self.assertEqual(failures, [])

    def test_rejects_each_metric_independently(self):
        failures = self.verify(
            {
                "percent_statements_covered": 99.99,
                "missing_lines": 1,
                "percent_branches_covered": 100,
                "missing_branches": 0,
            },
            "100",
        )
        self.assertTrue(any("statements coverage" in failure for failure in failures))
        self.assertFalse(any("branches coverage" in failure for failure in failures))

    def test_rejects_inconsistent_missing_counts_at_full_gate(self):
        failures = self.verify(
            {
                "percent_statements_covered": 100,
                "missing_lines": 0,
                "percent_branches_covered": 100,
                "missing_branches": 1,
            },
            "100",
        )
        self.assertEqual(
            failures, ["branches coverage reports 1 missing item(s) at a 100% gate"]
        )

    def test_allows_configured_lower_threshold(self):
        failures = self.verify(
            {
                "percent_statements_covered": 95,
                "missing_lines": 3,
                "percent_branches_covered": 94.5,
                "missing_branches": 2,
            },
            "90",
        )
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
