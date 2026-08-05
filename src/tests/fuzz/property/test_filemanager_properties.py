"""Filesystem containment properties for FileManager."""

import os
import tempfile
import unittest

from hypothesis import given, strategies as st

from services.filemanager import FileManager


class FileManagerPropertiesTest(unittest.TestCase):
    @given(st.text(max_size=100))
    def test_every_accepted_path_resolves_inside_base(self, filename: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = os.path.join(temp_dir, "managed")
            os.mkdir(base_dir)
            manager = FileManager(base_dir)

            if not manager._is_safe_path(filename):
                return

            filepath = manager.get_filepath(filename)
            self.assertIsNotNone(filepath)
            resolved = os.path.realpath(filepath)
            self.assertEqual(
                os.path.commonpath([manager.basepath, resolved]),
                manager.basepath,
            )

    def test_intermediate_symlink_cannot_escape_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = os.path.join(temp_dir, "managed")
            outside_dir = os.path.join(temp_dir, "outside")
            os.mkdir(base_dir)
            os.mkdir(outside_dir)
            os.symlink(outside_dir, os.path.join(base_dir, "escape"))
            manager = FileManager(base_dir)

            self.assertFalse(manager._is_safe_path("escape/new-file.txt"))
            self.assertIsNone(manager.get_filepath("escape/new-file.txt"))

    def test_null_byte_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FileManager(temp_dir)

            self.assertFalse(manager._is_safe_path("file\0.txt"))
            self.assertIsNone(manager.get_filepath("file\0.txt"))

    @given(st.sampled_from(["../outside", "/tmp/outside", "nested/../../outside"]))
    def test_known_traversal_shapes_are_rejected(self, filename: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FileManager(temp_dir)

            self.assertFalse(manager._is_safe_path(filename))
