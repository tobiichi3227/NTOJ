import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.manage.pro.filemanager import ManageProFilemanagerHandler
from handlers.prospec.batch.code import BatchCodeHandler
from handlers.prospec.batch.filemanager import BatchFilemanagerHandler
from services.chal import ChalService, Compiler
from services.code import CodeService
from services.pro import ProConst, ProService, ProType
from tests.unit.handlers.test_coverage_completion_contest_general_acct import (
    Subject,
    original,
)


def handler_subject(arguments=None):
    subject = Subject(arguments=arguments)
    subject.application = MagicMock()
    subject.request = SimpleNamespace(remote_ip="127.0.0.1")
    subject.db = MagicMock()
    subject.set_header = MagicMock()
    subject.write = MagicMock()
    subject.finish = MagicMock()
    return subject


class TestBatchCodeCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.challenges = SimpleNamespace(get_chal=AsyncMock())
        self.codes = SimpleNamespace(get_code=AsyncMock())
        for service, value in (
            (ChalService, self.challenges),
            (CodeService, self.codes),
        ):
            active = patch.object(service, "inst", value, create=True)
            active.start()
            self.addCleanup(active.stop)

    async def test_get_validation_service_type_and_success(self):
        method = original(BatchCodeHandler.get)
        self.assertEqual(
            (await method(handler_subject({"chal_id": "bad"})))[0],
            "Eparam",
        )

        self.challenges.get_chal.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            (await method(handler_subject({"chal_id": "1"})))[0],
            "Enoext",
        )

        wrong = SimpleNamespace(
            pro=SimpleNamespace(problem_type=ProType.COMMUNICATION)
        )
        self.challenges.get_chal.return_value = (None, wrong)
        self.assertEqual(
            (await method(handler_subject({"chal_id": "1"})))[0],
            "Eparam",
        )

        challenge = SimpleNamespace(
            pro=SimpleNamespace(problem_type=ProType.BATCH)
        )
        self.challenges.get_chal.return_value = (None, challenge)
        subject = handler_subject({"chal_id": "1"})
        await method(subject)
        subject.render.assert_awaited_once_with(
            "prospec/batch/code", title=None, chal=challenge
        )

    async def test_post_validation_service_error_and_language_mapping(self):
        method = original(BatchCodeHandler.post)
        self.assertEqual(
            (await method(handler_subject({"chal_id": "bad"})))[0],
            "Eparam",
        )

        self.codes.get_code.return_value = (
            ("Eacces", "denied"),
            None,
            None,
        )
        self.assertEqual(
            (await method(handler_subject({"chal_id": "1"})))[0],
            "Eacces",
        )

        cases = (
            (Compiler.GPP, "cpp"),
            (Compiler.RUST, "rust"),
            (Compiler.PYTHON3, "python"),
            (Compiler.JAVA, "java"),
            (999, "cpp"),
        )
        for compiler, language in cases:
            with self.subTest(compiler=compiler):
                self.codes.get_code.return_value = (
                    None,
                    "<main>",
                    compiler,
                )
                subject = handler_subject({"chal_id": "1"})
                await method(subject)
                status, payload = subject.error.call_args.args[0]
                self.assertEqual(status, "S")
                self.assertEqual(payload["compiler_type"], language)
                self.assertEqual(payload["code"], "&lt;main&gt;")


class TestBatchFilemanagerCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.problems = SimpleNamespace(get_pro=AsyncMock())
        active = patch.object(
            ProService, "inst", self.problems, create=True
        )
        active.start()
        self.addCleanup(active.stop)
        self.problem = SimpleNamespace(
            config=SimpleNamespace(spec_config=SimpleNamespace())
        )

    async def test_get_invalid_id_and_service_error(self):
        method = original(BatchFilemanagerHandler.get)
        self.assertEqual(
            (await method(handler_subject({"proid": "bad"})))[0],
            "Eparam",
        )

        self.problems.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            (await method(handler_subject({"proid": "1"})))[0],
            "Enoext",
        )

    async def test_download_suspicious_path_and_stream_failure(self):
        import handlers.prospec.batch.filemanager as module

        subject = handler_subject(
            {"path": "res/testdata", "filename": "input.txt"}
        )
        manager = MagicMock()
        manager.exists.return_value = True
        manager.get_filepath.return_value = None

        with (
            patch.object(module, "BatchConfig", object),
            patch.object(
                module.batch_spec,
                "get_allowed_file_paths",
                return_value={"res/testdata"},
            ),
            patch.object(module, "FileManager", return_value=manager),
        ):
            self.assertEqual(
                (
                    await BatchFilemanagerHandler._handle_download(
                        subject, 1, self.problem
                    )
                )[0],
                "Eacces",
            )

        manager.get_filepath.return_value = "/tmp/input.txt"
        stream = MagicMock()
        stream.__enter__.return_value = stream
        stream.__exit__.return_value = None
        stream.read.side_effect = OSError("read failed")
        subject = handler_subject(
            {"path": "res/testdata", "filename": "input.txt"}
        )
        with (
            patch.object(module, "BatchConfig", object),
            patch.object(
                module.batch_spec,
                "get_allowed_file_paths",
                return_value={"res/testdata"},
            ),
            patch.object(module, "FileManager", return_value=manager),
            patch("builtins.open", return_value=stream),
        ):
            self.assertEqual(
                (
                    await BatchFilemanagerHandler._handle_download(
                        subject, 1, self.problem
                    )
                )[0],
                "Eunk",
            )
        subject.add_log.assert_awaited()

    async def test_action_invalid_identifiers(self):
        cases = (
            (
                BatchFilemanagerHandler.preview_action,
                {
                    "pro_id": "bad",
                    "path": "res/testdata",
                    "filename": "a",
                },
            ),
            (
                BatchFilemanagerHandler.rename_single_file_action,
                {
                    "pro_id": "bad",
                    "path": "res/testdata",
                    "old_filename": "a",
                    "new_filename": "b",
                },
            ),
            (
                BatchFilemanagerHandler.update_single_file_action,
                {
                    "pro_id": "bad",
                    "path": "res/testdata",
                    "filename": "a",
                    "pack_token": "p",
                },
            ),
            (
                BatchFilemanagerHandler.add_single_file_action,
                {
                    "pro_id": "bad",
                    "path": "res/testdata",
                    "filename": "a",
                    "pack_token": "p",
                },
            ),
            (
                BatchFilemanagerHandler.delete_single_file_action,
                {
                    "pro_id": "bad",
                    "path": "res/testdata",
                    "filename": "a",
                },
            ),
        )
        for method, arguments in cases:
            with self.subTest(method=method.__name__):
                self.assertEqual(
                    (await method(handler_subject(arguments)))[0],
                    "Eparam",
                )

    async def test_action_problem_lookup_errors(self):
        self.problems.get_pro.return_value = (("Enoext", "missing"), None)
        cases = (
            (
                BatchFilemanagerHandler.preview_action,
                {
                    "pro_id": "1",
                    "path": "res/testdata",
                    "filename": "a",
                },
            ),
            (
                BatchFilemanagerHandler.rename_single_file_action,
                {
                    "pro_id": "1",
                    "path": "res/testdata",
                    "old_filename": "a",
                    "new_filename": "b",
                },
            ),
            (
                BatchFilemanagerHandler.update_single_file_action,
                {
                    "pro_id": "1",
                    "path": "res/testdata",
                    "filename": "a",
                    "pack_token": "p",
                },
            ),
            (
                BatchFilemanagerHandler.add_single_file_action,
                {
                    "pro_id": "1",
                    "path": "res/testdata",
                    "filename": "a",
                    "pack_token": "p",
                },
            ),
            (
                BatchFilemanagerHandler.delete_single_file_action,
                {
                    "pro_id": "1",
                    "path": "res/testdata",
                    "filename": "a",
                },
            ),
        )
        for method, arguments in cases:
            with self.subTest(method=method.__name__):
                self.assertEqual(
                    (await method(handler_subject(arguments)))[0],
                    "Enoext",
                )


class TestProblemFilemanagerRoutingCompletion(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self):
        self.problems = SimpleNamespace(get_pro=AsyncMock())
        active = patch.object(
            ProService, "inst", self.problems, create=True
        )
        active.start()
        self.addCleanup(active.stop)

    async def test_non_batch_post_routes(self):
        routes = (
            (
                ProType.COMMUNICATION,
                "handlers.prospec.communication.filemanager",
                "CommunicationFilemanagerHandler",
            ),
            (
                ProType.TWOSTEP,
                "handlers.prospec.twostep.filemanager",
                "TwoStepFilemanagerHandler",
            ),
            (
                ProType.OUTPUTONLY,
                "handlers.prospec.outputonly.filemanager",
                "OutputOnlyFilemanagerHandler",
            ),
        )
        real_import = __import__
        for problem_type, module_name, class_name in routes:
            with self.subTest(problem_type=problem_type):
                self.problems.get_pro.return_value = (
                    None,
                    SimpleNamespace(problem_type=problem_type),
                )
                fake_module = types.ModuleType(module_name)

                class RoutedHandler:
                    def __init__(self, *args, **kwargs):
                        self.acct = None
                        self._transforms = None

                    async def post(self):
                        return problem_type

                setattr(fake_module, class_name, RoutedHandler)

                def import_module(
                    name,
                    globals=None,
                    locals=None,
                    fromlist=(),
                    level=0,
                ):
                    if name == module_name:
                        return fake_module
                    return real_import(
                        name, globals, locals, fromlist, level
                    )

                subject = handler_subject({"pro_id": "1"})
                with patch("builtins.__import__", side_effect=import_module):
                    result = await original(
                        ManageProFilemanagerHandler.post
                    )(subject)
                self.assertEqual(result, problem_type)

    async def test_post_invalid_id_lookup_error_and_unknown_type(self):
        method = original(ManageProFilemanagerHandler.post)
        self.assertEqual(
            (await method(handler_subject({"pro_id": "bad"})))[0],
            "Eparam",
        )

        self.problems.get_pro.return_value = (("Enoext", "missing"), None)
        self.assertEqual(
            (await method(handler_subject({"pro_id": "1"})))[0],
            "Enoext",
        )

        self.problems.get_pro.return_value = (
            None,
            SimpleNamespace(problem_type=999),
        )
        self.assertEqual(
            (await method(handler_subject({"pro_id": "1"})))[0],
            "Enotsupport",
        )


if __name__ == "__main__":
    unittest.main()
