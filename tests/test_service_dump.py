import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from xray_lib import service  # noqa: E402


class ServiceDumpTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.old_etc_dir = service.ETC_DIR
        service.ETC_DIR = os.path.join(self.tmp_dir.name, "etc")
        self.addCleanup(self._restore_etc_dir)
        os.makedirs(service.ETC_DIR)

    def _restore_etc_dir(self):
        service.ETC_DIR = self.old_etc_dir

    def _write_config(self, name, content):
        path = os.path.join(service.ETC_DIR, f"{name}.yaml")
        with open(path, "w") as file_obj:
            file_obj.write(content)
        return path

    def test_dump_copies_config_then_generates_and_enables_target(self):
        self._write_config("alpha", "name: alpha\n")

        with mock.patch.object(service, "build_editor_cmd", return_value=["editor"]) as editor_mock:
            with mock.patch.object(
                service.subprocess,
                "run",
                return_value=mock.Mock(returncode=0),
            ) as run_mock:
                with mock.patch.object(service, "gen_config", return_value=True) as gen_mock:
                    with mock.patch.object(service, "run_as_root") as root_mock:
                        with mock.patch.object(service, "cmd_enable", return_value=0) as enable_mock:
                            result = service.cmd_dump("alpha", "beta")

        self.assertEqual(result, 0)
        with open(os.path.join(service.ETC_DIR, "beta.yaml")) as file_obj:
            self.assertEqual(file_obj.read(), "name: alpha\n")
        editor_mock.assert_called_once_with(os.path.join(service.ETC_DIR, "beta.yaml"))
        run_mock.assert_called_once_with(["editor"])
        gen_mock.assert_called_once_with("beta")
        root_mock.assert_called_once_with("systemctl", "daemon-reload")
        enable_mock.assert_called_once_with("beta")

    def test_dump_fails_when_source_config_missing(self):
        result = service.cmd_dump("missing", "beta")

        self.assertEqual(result, 1)
        self.assertFalse(os.path.exists(os.path.join(service.ETC_DIR, "beta.yaml")))

    def test_dump_fails_when_target_config_exists(self):
        self._write_config("alpha", "name: alpha\n")
        self._write_config("beta", "name: beta\n")

        result = service.cmd_dump("alpha", "beta")

        self.assertEqual(result, 1)
        with open(os.path.join(service.ETC_DIR, "beta.yaml")) as file_obj:
            self.assertEqual(file_obj.read(), "name: beta\n")


if __name__ == "__main__":
    unittest.main()
