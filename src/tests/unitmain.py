import unittest


def main():
    loader = unittest.TestLoader()
    unit_suite = unittest.TestSuite()
    for start_dir in ("tests/unit/services", "tests/unit/handlers"):
        unit_suite.addTests(loader.discover(start_dir, pattern="test_*.py"))
    return unittest.TextTestRunner().run(unit_suite)

