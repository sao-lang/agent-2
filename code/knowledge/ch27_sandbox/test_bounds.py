"""四条边界的离线测试：不联网、不发真实请求、临时目录建在脚本旁边。

运行：python code/knowledge/ch27_sandbox/test_bounds.py
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from exec_bounds import cap_output
from network_bounds import check_url
from path_checks import BASE as PATH_DEMO_BASE
from path_checks import v1_prefix, v4_resolve

ROOT = Path(__file__).resolve().parent / ".test-workspace"


class PathBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)
        (ROOT / "sub").mkdir(parents=True)
        (ROOT / "notes.txt").write_text("ok", encoding="utf-8")
        (PATH_DEMO_BASE / "outside").mkdir(parents=True, exist_ok=True)
        (PATH_DEMO_BASE / "outside" / "secret.txt").write_text("no", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)
        shutil.rmtree(PATH_DEMO_BASE, ignore_errors=True)

    def test_inside_allowed(self) -> None:
        self.assertTrue(v4_resolve(ROOT, "sub/../notes.txt"))

    def test_traversal_refused(self) -> None:
        self.assertFalse(v4_resolve(ROOT, "../outside/secret.txt"))

    def test_naive_check_is_wrong(self) -> None:
        # 记录前缀检查的漏洞：它不是我们想要的判据
        escaped = [
            p
            for p in ("../outside/secret.txt", "sub/../../outside/secret.txt")
            if v1_prefix(ROOT, p) and not v4_resolve(ROOT, p)
        ]
        self.assertGreaterEqual(len(escaped), 1)

    def test_relative_root_breaks_check(self) -> None:
        # 根是相对路径时，解析结果永远不可能是它的子路径：判定全部失败
        relative = Path(ROOT.name)
        self.assertFalse(v4_resolve(relative, "notes.txt"))


class NetworkBoundaryTest(unittest.TestCase):
    def test_allowlisted_host_passes(self) -> None:
        self.assertIsNone(check_url("https://api.example.com/v1/orders"))

    def test_private_address_refused(self) -> None:
        why = check_url("https://intra.example.com/x")
        self.assertIsNotNone(why)
        self.assertIn("私有地址", why or "")

    def test_metadata_address_refused(self) -> None:
        self.assertIsNotNone(check_url("https://169.254.169.254/latest/meta-data/"))
        self.assertIsNotNone(check_url("https://2852039166/latest/meta-data/"))

    def test_unresolvable_refused(self) -> None:
        self.assertIn("解析失败", check_url("https://unknown.example.com/x") or "")

    def test_userinfo_refused(self) -> None:
        self.assertIn("userinfo", check_url("https://api.example.com@evil.com/x") or "")


class ResourceBoundaryTest(unittest.TestCase):
    def test_cap(self) -> None:
        text, truncated, total = cap_output(["a" * 5000], 4096)
        self.assertTrue(truncated)
        self.assertEqual(total, 5000)
        self.assertEqual(len(text.encode("utf-8")), 4096)


if __name__ == "__main__":
    unittest.main(verbosity=2)
