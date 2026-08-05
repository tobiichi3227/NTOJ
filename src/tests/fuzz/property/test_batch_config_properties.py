"""Serialization properties for Batch judge configuration."""

import json
import unittest

from hypothesis import given, strategies as st

from services.chal import Compiler
from services.pro import CheckerType, SummaryType
from services.prospec.batch import BatchConfig, BatchProblemSpec

compiler = st.sampled_from(list(Compiler))
optional_compiler = st.one_of(st.none(), compiler)
short_text = st.text(max_size=80)


class BatchConfigPropertiesTest(unittest.TestCase):
    @given(
        chalmeta=short_text,
        userprog_compile_args=short_text,
        checker_type=st.sampled_from(list(CheckerType)),
        checker_compiler=optional_compiler,
        checker_compile_args=short_text,
        summary_type=st.sampled_from(list(SummaryType)),
        summary_compiler=optional_compiler,
        summary_compile_args=short_text,
        has_grader=st.booleans(),
        allow_compilers=st.sets(compiler),
    )
    def test_json_round_trip_preserves_config(
        self,
        chalmeta: str,
        userprog_compile_args: str,
        checker_type: CheckerType,
        checker_compiler: Compiler | None,
        checker_compile_args: str,
        summary_type: SummaryType,
        summary_compiler: Compiler | None,
        summary_compile_args: str,
        has_grader: bool,
        allow_compilers: set[Compiler],
    ) -> None:
        config = BatchConfig(
            chalmeta=chalmeta,
            userprog_compile_args=userprog_compile_args,
            checker_type=checker_type,
            checker_compiler=checker_compiler,
            checker_compile_args=checker_compile_args,
            summary_type=summary_type,
            summary_compiler=summary_compiler,
            summary_compile_args=summary_compile_args,
            has_grader=has_grader,
            allow_compilers=allow_compilers,
        )
        spec = BatchProblemSpec()

        json_data = json.loads(json.dumps(spec.to_json(config)))

        self.assertEqual(spec.from_json(json_data), config)
