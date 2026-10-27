"""验证安装包边界，并独立运行其中的后端。"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.package_plugin import package_plugin  # noqa: E402


class PackageTests(unittest.TestCase):
    def setUp(self) -> None:
        """创建包含真实后端文件和最小构建资源的源码目录。"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout"
        self.root.mkdir()
        self.output = Path(self.temp.name) / "dist"
        for name in (
            "main.py",
            "metadata.yaml",
            "_conf_schema.json",
            "LICENSE-MIT",
            "LICENSE-APACHE",
            "store/schema.sql",
        ):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        for directory in (
            "app",
            "adapters",
            "core",
            "store",
            "recall",
            "perceive",
            "maintain",
            "webui",
            "services",
        ):
            for source in (ROOT / directory).rglob("*.py"):
                target = self.root / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        self.view = self.root / "pages/memory"
        (self.view / "assets").mkdir(parents=True)
        (self.view / "index.html").write_text(
            '<link href="./assets/app.css"><script src="./assets/app.js"></script>',
            encoding="utf-8",
        )
        (self.view / "LICENSES.md").write_text("Fixture licenses", encoding="utf-8")
        (self.view / "ASSET-LICENSES.txt").write_text(
            "Fixture asset licenses", encoding="utf-8"
        )
        (self.view / "assets/app.js").write_text(
            "console.log('production')", encoding="utf-8"
        )
        (self.view / "assets/app.css").write_text(
            "body { color: black }", encoding="utf-8"
        )
        (self.root / ".gitignore").write_text("/pages/\n", encoding="utf-8")
        for name in (
            ".env",
            "core/private.db",
            "tests/fixture.py",
            "dashboard/src/demo.ts",
            "openapi.yaml",
            "requirements-dev.txt",
            "dashboard/src/contracts/generated.ts",
            "dashboard/tools/api-codegen/package.json",
            "dashboard/node_modules/.tmp/backend-contract.json",
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not distributable", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "add", "."], check=True, capture_output=True
        )
        (self.root / "core/untracked.py").write_text(
            "local_only = True", encoding="utf-8"
        )

    def test_runtime_allowlist_and_reproducible_checksum(self) -> None:
        """排除开发及本地文件，保留运行资源。"""
        archive = package_plugin(self.root, self.output)
        first = archive.read_bytes()
        with ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            self.assertTrue(
                {
                    "main.py",
                    "app/checkpoint.py",
                    "app/contracts.py",
                    "adapters/astrbot_hooks.py",
                    "adapters/astrbot_plugin.py",
                    "adapters/seekmemory_context.py",
                    "services/access_service.py",
                    "services/ingest_service.py",
                    "store/schema.sql",
                    "pages/memory/index.html",
                }
                <= names
            )
            self.assertTrue(
                {"LICENSE-MIT", "LICENSE-APACHE", "pages/memory/LICENSES.md"} <= names
            )
            self.assertFalse(
                {
                    ".env",
                    "core/private.db",
                    "core/untracked.py",
                    "tests/fixture.py",
                    "dashboard/src/demo.ts",
                    "openapi.yaml",
                    "requirements-dev.txt",
                    "dashboard/src/contracts/generated.ts",
                    "dashboard/tools/api-codegen/package.json",
                    "dashboard/node_modules/.tmp/backend-contract.json",
                }
                & names
            )
            self.assertIsNone(bundle.testzip())
        self.assertEqual(first, package_plugin(self.root, self.output).read_bytes())
        self.assertEqual(
            (self.output / "SHA256SUMS").read_text(encoding="utf-8"),
            f"{hashlib.sha256(first).hexdigest()}  {archive.name}\n",
        )

    def test_missing_runtime_resource_fails(self) -> None:
        """SQL 表结构缺失时不生成 ZIP。"""
        (self.root / "store/schema.sql").unlink()
        with self.assertRaisesRegex(ValueError, "运行文件缺失或为空"):
            package_plugin(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_or_unbuilt_frontend_fails(self) -> None:
        """要求包含生产资源、许可证声明及可解析的入口 URL。"""
        for name in (
            "index.html",
            "LICENSES.md",
            "ASSET-LICENSES.txt",
            "assets/app.js",
            "assets/app.css",
        ):
            with self.subTest(name=name):
                path = self.view / name
                contents = path.read_bytes()
                path.unlink()
                with self.assertRaises(ValueError):
                    package_plugin(self.root, self.output)
                path.write_bytes(contents)
        (self.view / "index.html").write_text(
            '<script src="/src/main.tsx"></script>', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "相对路径引用已打包的生产资源"):
            package_plugin(self.root, self.output)

    def test_tag_must_match_metadata(self) -> None:
        """标签必须对应安装包中实际包含的版本。"""
        (self.root / "metadata.yaml").write_text(
            'version: "1.2.3-rc.1"\n', encoding="utf-8"
        )
        package_plugin(self.root, self.output, "v1.2.3-rc.1")
        with self.assertRaisesRegex(ValueError, "不匹配"):
            package_plugin(self.root, self.output, "v1.2.3")

    def test_missing_font_reference_fails(self) -> None:
        """入口有效时仍需检查 CSS 引用的次级资源是否缺失。"""
        (self.view / "assets/app.css").write_text(
            '@font-face { src: url("./missing.woff2") }', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "CSS 引用了未打包"):
            package_plugin(self.root, self.output)

    def test_source_maps_and_mock_bundles_fail(self) -> None:
        """防止开发数据和源码映射进入发布资源。"""
        source_map = self.view / "assets/app.js.map"
        source_map.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "构建资源类型不受支持"):
            package_plugin(self.root, self.output)
        source_map.unlink()
        (self.view / "assets/app.js").write_text(
            'const id = "mock_memory_001"', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "开发代码"):
            package_plugin(self.root, self.output)

    def test_backend_runs_from_extracted_archive(self) -> None:
        """脱离源码目录，对解压文件执行冒烟测试。"""
        archive = package_plugin(self.root, self.output)
        installed = Path(self.temp.name) / "installed"
        with ZipFile(archive) as bundle:
            bundle.extractall(installed)
        # 测试框架位于分发 ZIP 之外。
        (installed / "tests").mkdir()
        shutil.copyfile(ROOT / "tests/test_smoke.py", installed / "tests/test_smoke.py")
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-I",
                str(installed / "tests/test_smoke.py"),
            ],
            cwd=installed,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        probe = installed / "tests" / "test_seekmemory_context_import.py"
        probe.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
            "from adapters.seekmemory_context import SeekMemoryContextAdapter\n"
            "from app.runtime import MemoryContext, MemoryContextRequest\n"
            "context = SeekMemoryContextAdapter(lambda event: MemoryContext(\n"
            "    text='block', info={'final_ids': ('a1',)}\n"
            ")).build_context(MemoryContextRequest('s1', 'hello'))\n"
            "assert context.text == 'block'\n"
            "assert context.info['final_ids'] == ('a1',)\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-I", str(probe)],
            cwd=installed,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
