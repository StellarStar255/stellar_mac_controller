"""把 mac_tools 包装成一个最小的 stdio MCP 服务，给本机 Claude Code 和 Codex 使用。

协议：一行一个 JSON-RPC 消息。只实现 initialize / tools/list / tools/call / ping。
stdout 只能输出协议消息，日志一律写 stderr。
"""
import json
import sys

import mac_tools


def _reply(msg_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle(req):
    method, params = req.get("method"), req.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mac", "version": "0.1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": s} for n, _, d, s in mac_tools.TOOLS]}
    if method == "tools/call":
        parts, is_error = mac_tools.run_tool(params.get("name"), params.get("arguments") or {})
        content = [{"type": "text", "text": p[1]} if p[0] == "text"
                   else {"type": "image", "data": p[1], "mimeType": p[2]} for p in parts]
        return {"content": content, "isError": is_error}
    raise LookupError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in req:          # 通知（如 notifications/initialized），不需要回复
            continue
        try:
            _reply(req["id"], _handle(req))
        except LookupError as e:
            _reply(req["id"], error={"code": -32601, "message": f"Method not found: {e}"})
        except Exception as e:  # noqa: BLE001
            print(f"[mac-mcp] {e!r}", file=sys.stderr)
            _reply(req["id"], error={"code": -32603, "message": str(e)})


if __name__ == "__main__":
    main()
