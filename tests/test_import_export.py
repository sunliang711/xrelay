import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from xray_lib import import_export  # noqa: E402


class ImportExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.old_etc_dir = import_export.ETC_DIR
        import_export.ETC_DIR = os.path.join(self.tmp_dir.name, "etc")
        self.addCleanup(self._restore_etc_dir)
        os.makedirs(import_export.ETC_DIR)

    def _restore_etc_dir(self):
        import_export.ETC_DIR = self.old_etc_dir

    def _write_config(self, name, content):
        path = os.path.join(import_export.ETC_DIR, f"{name}.yaml")
        with open(path, "w") as file_obj:
            file_obj.write(content)
        return path

    def test_export_selected_configs(self):
        self._write_config("alpha", "name: alpha\n")
        self._write_config("beta", "name: beta\n")
        output = os.path.join(self.tmp_dir.name, "selected.zip")

        result = import_export.cmd_export(["alpha"], output, False, False)

        self.assertEqual(result, 0)
        with zipfile.ZipFile(output) as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("configs/alpha.yaml", archive.namelist())
            self.assertNotIn("configs/beta.yaml", archive.namelist())

    def test_export_defaults_to_all_configs(self):
        self._write_config("alpha", "name: alpha\n")
        self._write_config("beta", "name: beta\n")
        output = os.path.join(self.tmp_dir.name, "all.zip")

        result = import_export.cmd_export([], output, False, False)

        self.assertEqual(result, 0)
        with zipfile.ZipFile(output) as archive:
            self.assertIn("configs/alpha.yaml", archive.namelist())
            self.assertIn("configs/beta.yaml", archive.namelist())

    def test_import_skips_existing_configs(self):
        self._write_config("alpha", "old: true\n")
        source = os.path.join(self.tmp_dir.name, "source.zip")
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("configs/alpha.yaml", "new: false\n")
            archive.writestr("configs/beta.yaml", "new: true\n")

        result = import_export.cmd_import(source)

        self.assertEqual(result, 0)
        with open(os.path.join(import_export.ETC_DIR, "alpha.yaml")) as file_obj:
            self.assertEqual(file_obj.read(), "old: true\n")
        with open(os.path.join(import_export.ETC_DIR, "beta.yaml")) as file_obj:
            self.assertEqual(file_obj.read(), "new: true\n")


if __name__ == "__main__":
    unittest.main()
