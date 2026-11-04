"""后端一致性测试（P3 验收）：路径 jail 是安全关键件，用例最多。"""

from __future__ import annotations

import asyncio
import os
import shutil
import unittest
from pathlib import Path

from harness.contracts.types import ApprovalRequest, Decision, Document, ExecResult, Limits, Mount
from harness.impl.backends import (
    FakeClock,
    FakeSandbox,
    MemoryApprovalChannel,
    MemoryArtifactStore,
    MemoryFileSystem,
    MemoryIndex,
    MemoryQueue,
    MemorySecretBroker,
    PathDenied,
    resolve,
)
from harness.contracts.types import Namespace, Step

NS = Namespace(tenant="t1", user="u1", session="s1", agent="a")


def run(coro):
    return asyncio.run(coro)


class ResolveTest(unittest.TestCase):
    """SPEC M12.3：唯一的 jail 点。"""

    MOUNTS = (Mount("/work", None, "rw"), Mount("/readonly", None, "ro"))

    def test_longest_prefix_wins(self):
        res = resolve(self.MOUNTS, "/work/sub/a.txt")
        self.assertEqual(res.virtual, "/work/sub/a.txt")
        self.assertEqual(res.relative, "sub/a.txt")
        self.assertTrue(res.writable)

    def test_outside_mounts_denied(self):
        with self.assertRaises(PathDenied):
            resolve(self.MOUNTS, "/etc/passwd")

    def test_traversal_denied(self):
        with self.assertRaises(PathDenied):
            resolve((Mount("/work", None, "rw"),), "/work/../etc/passwd")

    def test_relative_path_denied(self):
        with self.assertRaises(PathDenied):
            resolve(self.MOUNTS, "work/a.txt")

    def test_readonly_mount(self):
        res = resolve(self.MOUNTS, "/readonly/x")
        self.assertFalse(res.writable)


class MemoryFsTest(unittest.TestCase):
    def setUp(self):
        self.fs = MemoryFileSystem()

    def test_write_read_roundtrip(self):
        run(self.fs.write("/work/a.txt", b"hello"))
        self.assertEqual(run(self.fs.read("/work/a.txt")), b"hello")

    def test_write_outside_denied(self):
        with self.assertRaises(PathDenied):
            run(self.fs.write("/etc/passwd", b"x"))

    def test_traversal_denied(self):
        with self.assertRaises(PathDenied):
            run(self.fs.write("/work/../../x", b"x"))

    def test_readonly_write_denied(self):
        fs = MemoryFileSystem(mounts=(Mount("/ro", None, "ro"),))
        with self.assertRaises(PathDenied):
            run(fs.write("/ro/x", b"x"))

    def test_edit_and_grep(self):
        run(self.fs.write("/work/a.py", b"alpha\nbeta\n"))
        self.assertEqual(run(self.fs.edit("/work/a.py", "beta", "gamma")), 1)
        self.assertIn(b"gamma", run(self.fs.read("/work/a.py")))
        hits = run(self.fs.grep("gam"))
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].line, 2)

    def test_stat(self):
        run(self.fs.write("/work/a.txt", b"12345"))
        st = run(self.fs.stat("/work/a.txt"))
        self.assertEqual(st.size, 5)


class TempFsTest(unittest.TestCase):
    """本地实现也要走同一个 jail。

    用工作区内目录而非系统临时目录：沙箱环境下系统临时目录的清理会因权限失败。
    """

    def setUp(self):
        self.base = Path(__file__).parent / "_tmp_backends"
        shutil.rmtree(self.base, ignore_errors=True)
        self.root = self.base / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_read_write_inside_root(self):
        from harness.impl.backends import LocalFileSystem

        fs = LocalFileSystem((Mount("/work", str(self.root), "rw"),))
        run(fs.write("/work/sub/a.txt", b"hi"))
        self.assertEqual(run(fs.read("/work/sub/a.txt")), b"hi")

    def test_escape_denied(self):
        from harness.impl.backends import LocalFileSystem

        fs = LocalFileSystem((Mount("/work", str(self.root), "rw"),))
        with self.assertRaises(PathDenied):
            run(fs.write("/work/../escape.txt", b"x"))

    def test_symbolic_link_escape_denied(self):
        from harness.impl.backends import LocalFileSystem

        outside = self.base / "outside"
        outside.mkdir(exist_ok=True)
        link = self.root / "link"
        try:
            if link.exists():
                link.unlink()
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("当前平台不允许创建符号链接")
        fs = LocalFileSystem((Mount("/work", str(self.root), "rw"),))
        with self.assertRaises(PathDenied):
            run(fs.read("/work/link/secret.txt"))


class SandboxTest(unittest.TestCase):
    def test_fake_records_calls(self):
        sb = FakeSandbox({"ls": ExecResult(exit=0, stdout="a b")})
        self.assertEqual(run(sb.exec(["ls"])).stdout, "a b")
        self.assertEqual(sb.calls, [("ls",)])

    def test_local_sandbox_whitelist(self):
        from harness.impl.backends import LocalSandbox

        sb = LocalSandbox(allow=("echo",))
        with self.assertRaises(PermissionError):
            run(sb.exec(["rm", "-rf", "/"]))
        with self.assertRaises(PermissionError):
            run(sb.exec(["echo"], limits=Limits(network=True)))

    def test_split_never_returns_shell_string(self):
        from harness.impl.backends import LocalSandbox

        self.assertEqual(LocalSandbox.split("echo a b"), ["echo", "a", "b"])
        self.assertEqual(LocalSandbox.split('echo "a b"'), ["echo", "a b"])


class ArtifactTest(unittest.TestCase):
    def test_put_get(self):
        store = MemoryArtifactStore()
        ref = run(store.put("out.txt", b"payload"))
        self.assertTrue(ref.uri.startswith("artifact://"))
        self.assertEqual(run(store.get(ref)), b"payload")
        self.assertEqual(run(store.stat(ref)).ref.uri, ref.uri)


class SecretTest(unittest.TestCase):
    def test_get_and_list_hides_values(self):
        b = MemorySecretBroker({"GH_TOKEN": "s3cr3t"})
        self.assertEqual(run(b.get("GH_TOKEN")), "s3cr3t")
        self.assertEqual(run(b.list()), ["GH_TOKEN"])
        with self.assertRaises(KeyError):
            run(b.get("NOPE"))


class IndexTest(unittest.TestCase):
    def test_search_and_namespace_isolation(self):
        idx = MemoryIndex()
        run(idx.upsert(NS, [Document(id="1", text="退款政策 七天无理由")]))
        hits = run(idx.search(NS, "退款", k=3))
        self.assertEqual(len(hits), 1)
        other = Namespace(tenant="t2")
        self.assertEqual(run(idx.search(other, "退款", k=3)), [])

    def test_filters_pushed_down(self):
        idx = MemoryIndex()
        run(idx.upsert(NS, [
            Document(id="1", text="退款政策", metadata={"lang": "zh"}),
            Document(id="2", text="退款政策", metadata={"lang": "en"}),
        ]))
        hits = run(idx.search(NS, "退款", k=5, filters={"lang": "en"}))
        self.assertEqual([h.id for h in hits], ["2"])


class QueueTest(unittest.TestCase):
    def test_enqueue_dequeue_ack(self):
        from harness.contracts.types import Job

        q = MemoryQueue()
        run(q.enqueue(Job(id="j1", kind="run", dedup_key="d1")))
        run(q.enqueue(Job(id="j1", kind="run", dedup_key="d1")))   # 去重
        job = run(q.dequeue())
        self.assertEqual(job.id, "j1")
        run(q.ack("j1"))
        self.assertIsNone(run(q.dequeue()))


class ApprovalTest(unittest.TestCase):
    def test_request_wait_respond(self):
        ch = MemoryApprovalChannel()
        req = ApprovalRequest(id="", step=Step(id="s1", tool_name="refund"), reason="金额超限")
        approval_id = run(ch.request(req))

        async def scenario():
            task = asyncio.create_task(ch.wait(approval_id, timeout_s=1))
            await asyncio.sleep(0)
            await ch.respond(approval_id, Decision.approve("alice"))
            return await task

        decision = run(scenario())
        self.assertEqual(decision.action, "approve")
        self.assertEqual(decision.by, "alice")

    def test_timeout_returns_none(self):
        ch = MemoryApprovalChannel()
        approval_id = run(ch.request(ApprovalRequest(id="", step=Step(id="s1"))))
        self.assertIsNone(run(ch.wait(approval_id, timeout_s=0.01)))


class ClockTest(unittest.TestCase):
    def test_fake_clock_advances(self):
        clock = FakeClock()
        t0 = clock.now()
        clock.advance(60)
        self.assertEqual((clock.now() - t0).total_seconds(), 60)

    def test_system_clock_monotonic(self):
        from harness.impl.backends import SystemClock

        clock = SystemClock()
        self.assertLessEqual(clock.monotonic(), clock.monotonic())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
