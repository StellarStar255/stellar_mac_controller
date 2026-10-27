import json
import tempfile
import threading
import tomllib
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import backends
if sys.platform == "darwin":
    import Quartz
    with patch.object(Quartz, "CGDisplayBounds", return_value=SimpleNamespace(
            size=SimpleNamespace(width=1920, height=1080))):
        import mac_tools
else:
    import desktop_tools as mac_tools


class Signal:
    def __init__(self, hook=None):
        self.values = []
        self.hook = hook
        self.event = threading.Event()

    def emit(self, *args):
        self.values.append(args)
        if self.hook:
            self.hook(*args)
        self.event.set()


def bridge():
    return SimpleNamespace(**{k: Signal() for k in
                              ("text", "tool", "tool_result", "done", "error", "model", "reasoning", "busy")})


class BackendTests(unittest.TestCase):
    def test_external_tool_config_is_disabled_only_for_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "config"
            work = Path(tmp) / "work"
            home.mkdir()
            (work / ".codex").mkdir(parents=True)
            user_config = home / "config.toml"
            original = '[mcp_servers.node_repl]\ncommand="node"\n[plugins."unified-computer-use@openai-bundled"]\nenabled=true\n'
            user_config.write_text(original)
            (work / ".codex" / "config.toml").write_text('[mcp_servers."extra.server"]\ncommand="example"\n')
            with patch.dict(backends.os.environ, {"CODEX_HOME": str(home)}):
                backend = backends.CodexBackend(bridge())
                backend.workdir = str(work)
                cmd = backend._command([])
            config = tomllib.loads("\n".join(cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-c"))
            self.assertFalse(config["features"]["plugins"])
            self.assertFalse(config["features"]["computer_use"])
            self.assertFalse(config["mcp_servers"]["node_repl"]["enabled"])
            self.assertFalse(config["mcp_servers"]["extra.server"]["enabled"])
            self.assertFalse(config["plugins"]["unified-computer-use@openai-bundled"]["enabled"])
            self.assertTrue(config["mcp_servers"]["mac"]["enabled"])
            self.assertTrue(config["mcp_servers"]["mac"]["required"])
            self.assertEqual(user_config.read_text(), original)

    def test_retired_auto_mode_keeps_session_and_uses_cli_default(self):
        backend = backends.CodexBackend(bridge(), "my-model", reasoning_effort="auto")
        backend.load({"session_id": "thread-123", "last_auto_effort": "high"})
        self.assertEqual(backend.state(), {"session_id": "thread-123"})
        self.assertEqual(backend.reasoning_effort, "")
        self.assertFalse(any(arg.startswith("model_reasoning_effort=") for arg in backend._command([])))

    def test_reasoning_override_on_new_and_resumed_turns(self):
        backend = backends.CodexBackend(bridge(), "my-model", reasoning_effort="high")
        for state in ({}, {"session_id": "thread-123"}):
            backend.load(state)
            cmd = backend._command([])
            configs = tomllib.loads("\n".join(cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-c"))
            self.assertEqual(configs["model_reasoning_effort"], "high")
        backend.reasoning_effort = ""
        self.assertFalse(any(arg.startswith("model_reasoning_effort=") for arg in backend._command([])))

    def test_model_specific_reasoning_levels(self):
        with patch.object(backends, "codex_model_catalog", return_value={
                "model-a": {"supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}]},
                "model-b": {"supported_reasoning_levels": []}}):
            self.assertEqual(backends.codex_reasoning_levels("model-a"), ["low", "high"])
            self.assertEqual(backends.codex_reasoning_levels("model-b"), [])
            self.assertEqual(backends.codex_reasoning_levels("custom"), ["low", "medium", "high"])

    def test_command_resume_and_permissions(self):
        backend = backends.CodexBackend(bridge(), "custom-model", confirm_delete=True)
        backend.workdir = '/tmp/带空格 "目录"'
        backend.load({"session_id": "thread-123"})
        cmd = backend._command(["/tmp/photo.png", "/tmp/document.pdf"])
        configs = tomllib.loads("\n".join(cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-c"))
        self.assertEqual(configs["sandbox_mode"], "read-only")
        self.assertFalse(configs["features"]["shell_tool"])
        self.assertEqual(configs["mcp_servers"]["mac"]["default_tools_approval_mode"], "approve")
        env = configs["mcp_servers"]["mac"]["env"]
        self.assertEqual(env["MAC_CTRL_WORKDIR"], backend.workdir)
        self.assertEqual(env["MAC_CTRL_CONFIRM_DELETE"], "1")
        self.assertIn("resume", cmd)
        self.assertEqual(cmd[-2:], ["thread-123", "-"])
        self.assertEqual(cmd[cmd.index("--model") + 1], "custom-model")
        self.assertIn("/tmp/photo.png", cmd)
        self.assertNotIn("/tmp/document.pdf", cmd)

    @unittest.skipIf(sys.platform == "win32", "POSIX fake CLI fixture")
    def test_subprocess_queue_and_session_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-codex"
            fake.write_text(f"#!{backends.sys.executable}\n" + '''
import json, sys
from pathlib import Path
prompt = sys.stdin.read()
with Path("calls.jsonl").open("a") as log:
    log.write(json.dumps({"args": sys.argv[1:], "prompt": prompt}) + "\\n")
print(json.dumps({"type": "thread.started", "thread_id": "thread-123"}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "已完成"}}), flush=True)
print(json.dumps({"type": "turn.completed", "usage": {}}), flush=True)
''')
            fake.chmod(0o755)
            signals = bridge()
            backend = backends.CodexBackend(signals, "my-model", reasoning_effort="high")

            def queue(_):
                if len(signals.text.values) == 1:
                    backend.send("第二条消息：研究极氪全系列产品，写比较报告", workdir=tmp)

            signals.text.hook = queue
            with patch.object(backends, "CODEX", str(fake)):
                backend.send("打开备忘录", workdir=tmp)
                self.assertTrue(signals.done.event.wait(5))
            self.assertFalse(signals.error.values)
            self.assertFalse(backend.busy)
            self.assertEqual(backend.state(), {"session_id": "thread-123"})
            restored = backends.CodexBackend(bridge(), "my-model", reasoning_effort="high")
            restored.load(backend.state())
            self.assertEqual(restored.session_id, "thread-123")
            self.assertEqual(signals.reasoning.values, [("high",), ("high",)])
            calls = [json.loads(line) for line in (Path(tmp) / "calls.jsonl").read_text().splitlines()]
            self.assertEqual(len(calls), 2)
            self.assertIn("打开备忘录", calls[0]["prompt"])
            self.assertIn("第二条消息", calls[1]["prompt"])
            self.assertNotIn("resume", calls[0]["args"])
            self.assertIn("resume", calls[1]["args"])
            self.assertIn('model_reasoning_effort="high"', calls[0]["args"])
            self.assertIn('model_reasoning_effort="high"', calls[1]["args"])
            self.assertNotIn('model_reasoning_effort="auto"', calls[1]["args"])

    def test_mcp_error_and_turn_failure(self):
        signals = bridge()
        backend = backends.CodexBackend(signals)
        backend._handle_codex({"type": "item.completed", "item": {
            "type": "mcp_tool_call", "result": {"isError": True, "content": [
                {"type": "text", "text": "用户拒绝"}]}}})
        self.assertEqual(signals.tool_result.values, [(True, "用户拒绝")])
        self.assertEqual(backend._handle_codex({"type": "turn.failed", "error": {"message": "未登录"}}), "未登录")

    @unittest.skipIf(sys.platform == "win32", "POSIX fake CLI fixture")
    def test_stop_running_process_and_discard_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-codex"
            fake.write_text(f"#!{backends.sys.executable}\nimport sys, time\nsys.stdin.read()\ntime.sleep(30)\n")
            fake.chmod(0o755)
            signals = bridge()
            backend = backends.CodexBackend(signals, "my-model")
            with patch.object(backends, "CODEX", str(fake)):
                backend.send("任务", workdir=tmp)
                self.assertTrue(signals.model.event.wait(5))
                backend.send("排队消息", workdir=tmp)
                backend.stop()
                self.assertTrue(signals.done.event.wait(5))
            self.assertEqual(signals.done.values, [("已停止",)])
            self.assertFalse(signals.error.values)
            self.assertFalse(backend.busy)
            self.assertEqual(backend.pending, [])

    @unittest.skipIf(sys.platform == "win32", "POSIX fake CLI fixture")
    def test_computer_use_denial_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-codex"
            events = [
                {"type": "item.completed", "item": {
                    "type": "mcp_tool_call", "status": "failed", "result": {
                        "isError": True, "content": [{"type": "text", "text":
                            "Computer Use was not approved to use WeChat"}]}}},
                {"type": "turn.completed", "usage": {}},
            ]
            fake.write_text(f"#!{backends.sys.executable}\nimport sys\nsys.stdin.read()\n"
                            + "\n".join(f"print({json.dumps(json.dumps(ev))})" for ev in events) + "\n")
            fake.chmod(0o755)
            signals = bridge()
            backend = backends.CodexBackend(signals)
            with patch.object(backends, "CODEX", str(fake)):
                backend.send("查看应用", workdir=tmp)
                self.assertTrue(signals.error.event.wait(5))
            self.assertIn("Computer Use 未获应用访问授权：WeChat", signals.error.values[0][0])
            self.assertIn("设置 → Computer Use", signals.tool_result.values[0][1])
            self.assertFalse(signals.done.values)

    def test_computer_use_denial_excludes_appended_tool_documentation(self):
        for suffix in ("\n\n## Computer Use\nControl native apps", " ## Computer Use\nControl native apps"):
            signals = bridge()
            backend = backends.CodexBackend(signals)
            backend._handle_codex({"type": "item.completed", "item": {
                "type": "mcp_tool_call", "result": {"isError": True, "content": [
                    {"type": "text", "text": "Computer Use was not approved to use WeChat" + suffix}]}}})
            self.assertIn("授权：WeChat。", backend._access_denial)
            self.assertNotIn("##", backend._access_denial)
            self.assertNotIn("Control native apps", backend._access_denial)

    def test_delete_opt_out_preserves_other_risks(self):
        with patch.object(mac_tools, "CONFIRM_DELETE", False), patch.object(mac_tools, "confirm") as confirm:
            mac_tools.confirm_if_risky("命令", "rm -rf '/tmp/示例文件'", shell=True)
            confirm.assert_not_called()
            mac_tools.confirm_if_risky("命令", "sudo rm /tmp/example", shell=True)
            self.assertIn("管理员权限", confirm.call_args.args[1])
            confirm.reset_mock()
            mac_tools.confirm_if_risky("脚本", 'tell application "Finder" to empty trash', shell=False)
            confirm.assert_called_once()
        with patch.object(mac_tools, "CONFIRM_DELETE", True), patch.object(mac_tools, "confirm") as confirm:
            mac_tools.confirm_if_risky("命令", "rm /tmp/example", shell=True)
            confirm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
