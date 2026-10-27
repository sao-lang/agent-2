"""边界的离线单测：无网络、无真实外部服务，四条边界各测一条。

运行：
    python test_bounds.py          # 或者 python -m unittest -v test_bounds
解析器是注入的，路径根是临时目录，所以判定逻辑能在任何机器上跑。
"""

from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path

import network_bounds
from exec_bounds import cap_output
from path_escape import ATTEMPTS, v1_prefix, v4_resolve

FAKE_DNS = {
    "api.example.com": ["93.184.216.34"],
    "intra.example.com": ["10.0.0.7"],
}


def resolve(host: str) -> list[str]:
    return FAKE_DNS.get(host, [])


class PathBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        # 临时根建在当前目录下：不依赖系统临时目录可写（容器里它常是只读的）
        self.root = Path(f"_test_root_{os.getpid()}")
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir()
        (self.root / "notes.txt").write_text("ok", encoding="utf-8")
        # 判定用的根必须是解析后的绝对路径，下面有专门的用例证明这一条
        self.abs_root = self.root.resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_traversal_refused(self) -> None:
        self.assertFalse(v4_resolve(self.abs_root, "../outside/secret.txt"))

    def test_inside_allowed(self) -> None:
        self.assertTrue(v4_resolve(self.abs_root, "notes.txt"))

    def test_relative_root_breaks_check(self) -> None:
        # 根是相对路径时，解析结果永远不可能是它的子路径：判定全部失败
        self.assertFalse(v4_resolve(self.root, "notes.txt"))

    def test_naive_check_is_wrong(self) -> None:
        # 记录前缀检查的漏洞：它不是我们想要的判据
        escaped = [v for _, v in ATTEMPTS
                   if v1_prefix(self.abs_root, v) and not v4_resolve(self.abs_root, v)]
        self.assertGreaterEqual(len(escaped), 1)


class NetworkBoundaryTest(unittest.TestCase):
    def test_userinfo_refused(self) -> None:
        why = network_bounds.check_url("https://api.example.com@evil.com/x", resolve)
        self.assertIn("userinfo", why or "")

    def test_allowlisted_host_passes(self) -> None:
        self.assertIsNone(network_bounds.check_url("https://api.example.com/v1", resolve))

    def test_private_address_refused(self) -> None:
        why = network_bounds.check_url("https://intra.example.com/x", resolve)
        self.assertIn("10.0.0", why or "")

    def test_unresolvable_refused(self) -> None:
        self.assertIsNotNone(network_bounds.check_url("https://nope.example.com/x", resolve))


class ResourceTest(unittest.TestCase):
    def test_cap(self) -> None:
        text, truncated, total = cap_output(["a" * 100, "b" * 100], 64)
        self.assertTrue(truncated)
        self.assertEqual(len(text), 64)
        self.assertEqual(total, 200)


if __name__ == "__main__":
    unittest.main(verbosity=0)
