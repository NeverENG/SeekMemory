"""Exercise discovery and process isolation through the test-runner CLI.

通过测试运行脚本的命令行验证发现行为与进程隔离。
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestRunnerContractTest(unittest.TestCase):
    def run_fixture(self, files: dict[str, str]) -> subprocess.CompletedProcess:
        """Run a miniature repository without importing its tests here / 运行小型仓库，不在本进程导入其测试。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "tests").mkdir()
            shutil.copyfile(ROOT / "scripts/run_tests.py", root / "scripts/run_tests.py")
            shutil.copyfile(ROOT / "tests/layers.py", root / "tests/layers.py")
            for name, source in files.items():
                (root / "tests" / name).write_text(source, encoding="utf-8")
            return subprocess.run(
                [sys.executable, "-X", "utf8", "-B", str(root / "scripts/run_tests.py"), "--layer", "all"],
                capture_output=True, text=True, encoding="utf-8", cwd=root,
            )

    def test_late_definitions_run_once_and_failures_set_exit_status(self) -> None:
        for assertion, expected in (("self.assertTrue(True)", 0), ("self.fail('late failure')", 1)):
            with self.subTest(assertion=assertion):
                result = self.run_fixture({"test_late_unit.py": f"""
import unittest
class Early(unittest.TestCase):
    def test_early(self): print('EARLY_MARKER')
if __name__ == '__main__': raise SystemExit(99)
class Late(unittest.TestCase):
    def test_late(self):
        print('LATE_MARKER')
        {assertion}
"""})
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertEqual(result.stdout.count("EARLY_MARKER"), 1)
                self.assertEqual(result.stdout.count("LATE_MARKER"), 1)
                self.assertIn("Ran 2 tests", result.stderr)

    def test_fake_modules_cannot_leak_between_files(self) -> None:
        result = self.run_fixture({
            "test_a_unit.py": "import sys, unittest\nsys.modules['fake_sdk_marker'] = object()\nclass A(unittest.TestCase):\n def test_a(self): pass\n",
            "test_b_unit.py": "import sys, unittest\nclass B(unittest.TestCase):\n def test_b(self): self.assertNotIn('fake_sdk_marker', sys.modules)\n",
        })
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
