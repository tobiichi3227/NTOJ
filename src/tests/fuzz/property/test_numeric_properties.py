"""Properties and resource bounds for numeric range parsing."""

import unittest

from hypothesis import given, strategies as st

from utils.numeric import (
    MAX_PARSED_LIST_ITEMS,
    merge_list_to_str,
    parse_str_to_list,
)


class NumericPropertiesTest(unittest.TestCase):
    @given(st.lists(st.integers(min_value=0, max_value=100_000), max_size=200))
    def test_merge_parse_round_trip(self, nums: list[int]) -> None:
        expected = sorted(nums)

        encoded = merge_list_to_str(nums)

        self.assertEqual(parse_str_to_list(encoded), expected)

    @given(st.text(alphabet="0123456789,- ", max_size=200))
    def test_parser_is_bounded_or_rejects_input(self, value: str) -> None:
        try:
            parsed = parse_str_to_list(value, max_items=256)
        except ValueError as error:
            self.assertIn("item limit", str(error))
        else:
            self.assertLessEqual(len(parsed), 256)

    @given(st.text(max_size=100))
    def test_arbitrary_unicode_text_has_defined_outcome(self, value: str) -> None:
        try:
            parsed = parse_str_to_list(value, max_items=256)
        except ValueError as error:
            self.assertIn("item limit", str(error))
        else:
            self.assertIsInstance(parsed, list)
            self.assertLessEqual(len(parsed), 256)

    def test_oversized_range_is_rejected_before_materialization(self) -> None:
        with self.assertRaisesRegex(ValueError, "item limit"):
            parse_str_to_list(
                f"0-{MAX_PARSED_LIST_ITEMS}",
                max_items=MAX_PARSED_LIST_ITEMS,
            )

    def test_negative_item_limit_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be negative"):
            parse_str_to_list("1", max_items=-1)
