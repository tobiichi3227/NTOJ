import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.prospec.batch.judge import BatchJudgeHandler
from services.chal import Compiler
from services.pro import CheckerType, ProConst, ProService, ProType, SummaryType
from services.prospec.batch import batch_spec
from services.user import UserConst


def original(function):
    seen = set()
    while function.__name__ == "wrap" and function not in seen:
        seen.add(function)
        nested = [
            cell.cell_contents
            for cell in (function.__closure__ or ())
            if inspect.iscoroutinefunction(cell.cell_contents)
        ]
        if len(nested) != 1:
            raise AssertionError(f"Cannot unwrap {function}: {nested}")
        function = nested[0]
    return function


class Subject:
    def __init__(self, arguments=None, allow_compilers=None):
        self.arguments = arguments or {}
        self.allow_compilers = allow_compilers or []
        self.acct = MagicMock(
            acct_id=1, acct_type=UserConst.ACCTTYPE_KERNEL, name="admin"
        )
        self.error = MagicMock(side_effect=lambda value: value)
        self.add_log = AsyncMock(return_value=(None, 1))

    def get_argument(self, name, default=...):
        if name in self.arguments:
            return self.arguments[name]
        if default is not ...:
            return default
        raise KeyError(name)

    def get_arguments(self, name):
        if name != "allow_compilers[]":
            raise KeyError(name)
        return self.allow_compilers


def arguments(**overrides):
    values = {
        "pro_id": "5",
        "rate_precision": "2",
        "checker_type": str(int(CheckerType.DIFF)),
        "has_grader": "false",
        "userprog_compile_args": "-O2",
        "checker_compiler": "",
        "checker_compile_args": "",
        "summary_type": str(int(SummaryType.GROUPMIN)),
        "summary_compiler": "",
        "summary_compile_args": "",
        "chalmeta": "{}",
    }
    values.update(overrides)
    return values


def problem(problem_type=ProType.BATCH):
    return SimpleNamespace(
        problem_type=problem_type,
        config=SimpleNamespace(
            spec_config=batch_spec.get_default_config(), rate_precision=0
        ),
    )


class TestBatchJudgeHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pro = problem()
        self.pro_service = SimpleNamespace(
            get_pro=AsyncMock(return_value=(None, self.pro)),
            update_pro_config=AsyncMock(return_value=(None, None)),
        )
        active_patch = patch.object(ProService, "inst", self.pro_service, create=True)
        active_patch.start()
        self.addCleanup(active_patch.stop)
        self.post = original(BatchJudgeHandler.post)

    async def test_parameter_validation_matrix(self):
        cases = (
            ({"pro_id": "bad"}, "Invalid problem ID"),
            ({"rate_precision": "bad"}, "Invalid rate precision"),
            ({"rate_precision": str(ProConst.RATE_PRECISION_MAX + 1)}, "Invalid rate precision"),
            ({"checker_type": "999"}, "Invalid checker type"),
            ({"checker_compiler": "999"}, "Invalid checker compiler"),
            ({"summary_type": "999"}, "Invalid summary type"),
            ({"summary_compiler": "999"}, "Invalid summary compiler"),
            (
                {"checker_type": str(int(CheckerType.IOREDIR)), "chalmeta": "{"},
                "Challenge metadata json syntax error",
            ),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                result = await self.post(Subject(arguments(**overrides)))
                self.assertEqual(result[0], "Econf" if "metadata" in message else "Eparam")
                self.assertEqual(result[1], message)

    async def test_problem_lookup_type_and_update_errors(self):
        self.pro_service.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            await self.post(Subject(arguments())), ("Enoext", "missing")
        )

        self.pro_service.get_pro.return_value = (None, problem(ProType.OUTPUTONLY))
        self.assertEqual((await self.post(Subject(arguments())))[0], "Eparam")

        self.pro_service.get_pro.return_value = (None, self.pro)
        self.pro_service.update_pro_config.return_value = (("Edb", "down"), None)
        self.assertEqual(await self.post(Subject(arguments())), ("Edb", "down"))

    async def test_grader_directory_failure_duplicate_and_compiler_failure(self):
        grader_args = arguments(has_grader="true")
        subject = Subject(grader_args, [str(int(Compiler.GPP))])
        with patch("handlers.prospec.batch.judge.os.mkdir", side_effect=OSError("base")):
            self.assertEqual((await self.post(subject))[0], "Eunk")

        subject = Subject(grader_args, [str(int(Compiler.GPP))])
        with patch(
            "handlers.prospec.batch.judge.os.mkdir",
            side_effect=[None, OSError("compiler")],
        ):
            self.assertEqual((await self.post(subject))[0], "Eunk")

        subject = Subject(
            grader_args,
            [str(int(Compiler.GCC)), str(int(Compiler.CLANG)), "999"],
        )
        with patch(
            "handlers.prospec.batch.judge.os.mkdir",
            side_effect=[FileExistsError(), FileExistsError()],
        ) as mkdir:
            self.assertIsNone(await self.post(subject))
        self.assertEqual(mkdir.call_count, 2)
        self.assertEqual(
            self.pro.config.spec_config.allow_compilers,
            {int(Compiler.GCC), int(Compiler.CLANG)},
        )

    async def test_checker_and_summary_directory_errors(self):
        subject = Subject(
            arguments(checker_type=str(int(CheckerType.STD_TESTLIB)))
        )
        with patch("handlers.prospec.batch.judge.os.mkdir", side_effect=OSError("checker")):
            self.assertEqual((await self.post(subject))[0], "Eunk")

        subject = Subject(arguments(summary_type=str(int(SummaryType.CUSTOM))))
        with patch("handlers.prospec.batch.judge.os.mkdir", side_effect=OSError("summary")):
            self.assertEqual((await self.post(subject))[0], "Eunk")

    async def test_ioredir_custom_summary_success_updates_all_config_fields(self):
        subject = Subject(
            arguments(
                checker_type=str(int(CheckerType.IOREDIR)),
                checker_compiler=str(int(Compiler.GPP)),
                checker_compile_args="-D CHECK",
                summary_type=str(int(SummaryType.CUSTOM)),
                summary_compiler=str(int(Compiler.PYTHON3)),
                summary_compile_args="summary.py",
                chalmeta='{"mode":"pipe"}',
            ),
            [str(int(Compiler.GPP)), str(int(Compiler.PYTHON3))],
        )
        with patch(
            "handlers.prospec.batch.judge.os.mkdir", side_effect=FileExistsError()
        ):
            self.assertIsNone(await self.post(subject))
        config = self.pro.config
        self.assertEqual(config.rate_precision, 2)
        self.assertEqual(config.spec_config.checker_type, CheckerType.IOREDIR)
        self.assertEqual(config.spec_config.summary_type, SummaryType.CUSTOM)
        self.assertEqual(config.spec_config.chalmeta, '{"mode":"pipe"}')
        subject.add_log.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
