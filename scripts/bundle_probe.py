"""Launch an unpacked .mcpb bundle with its own manifest command and check that it answers MCP.

Reads ``<bundle>/manifest.json``, runs ``server.mcp_config`` (``command`` + ``args``, and ``env`` if any, with
``${__dirname}`` replaced by the bundle directory) and speaks MCP over stdio: ``initialize``, then ``tools/list``.
Exits 0 only when the server answers both and lists exactly the tools the manifest declares.

``.github/workflows/release.yml`` (job ``github-release``) runs it on the packed ``taxfill.mcpb`` once the published
``taxfill-mcp`` resolves from PyPI, before the bundle is attached to the GitHub release: the bundle's
``uv run --directory <bundle> src/server.py`` then installs that published server, as on a user's machine. It needs
``uv`` on PATH for that, and proves the manifest's own command, not what a given Claude Desktop build does with a
``server.type "uv"`` bundle.

    unzip -q taxfill.mcpb -d bundle && python scripts/bundle_probe.py bundle [--timeout 600]

Standard library only, so it runs under any Python 3.11+.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"


class ProbeError(RuntimeError):
    """The bundle did not start, did not answer, or listed other tools than its manifest declares."""


def _command(bundle: Path) -> tuple[list[str], dict[str, str], list[str]]:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    config = (manifest.get("server") or {}).get("mcp_config")
    if not config or not config.get("command"):
        raise ProbeError("manifest.json has no server.mcp_config.command to launch")
    here = str(bundle.resolve())

    def sub(value: str) -> str:
        return value.replace("${__dirname}", here)

    cmd = [sub(config["command"]), *(sub(a) for a in config.get("args", []))]
    env = {k: sub(v) for k, v in (config.get("env") or {}).items()}
    declared = sorted(t["name"] for t in manifest.get("tools", []))
    if not declared:
        raise ProbeError("manifest.json declares no tools to compare against")
    return cmd, env, declared


def probe(bundle: Path, timeout: float = 600.0) -> dict:
    """Launch the bundle, run initialize + tools/list; return {"server": serverInfo, "tools": [names]}.

    ``timeout`` bounds the whole exchange in seconds (the first launch installs the server and its dependencies).
    """
    cmd, extra_env, declared = _command(bundle)
    try:
        proc = subprocess.Popen(cmd, cwd=bundle, env={**os.environ, **extra_env}, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    except OSError as exc:
        raise ProbeError(f"could not start {cmd[0]!r}: {exc}") from exc
    lines: queue.Queue[str | None] = queue.Queue()
    stderr: list[str] = []

    def pump_stdout() -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    def pump_stderr() -> None:  # drained continuously: an installer's progress output must not fill the pipe
        for line in proc.stderr:
            stderr.append(line)

    threading.Thread(target=pump_stdout, daemon=True).start()
    threading.Thread(target=pump_stderr, daemon=True).start()
    deadline = time.monotonic() + timeout

    def fail(why: str) -> ProbeError:
        tail = "".join(stderr)[-3000:].rstrip()
        return ProbeError(f"{why} (command: {' '.join(cmd)})" + (f"\n--- server stderr (tail) ---\n{tail}" if tail else ""))

    def send(message: dict) -> None:
        try:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise fail(f"the server closed its stdin ({exc})") from exc

    def receive(want_id: int) -> dict:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise fail(f"no answer to request {want_id} within {timeout:g} s")
            try:
                line = lines.get(timeout=left)
            except queue.Empty:
                continue
            if line is None:
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                raise fail(f"the server exited (code {proc.returncode}) before answering request {want_id}")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                raise fail(f"the server wrote a non-JSON line to stdout: {line.strip()[:200]!r}") from None
            if message.get("id") != want_id:
                continue  # a notification or log message
            if "error" in message:
                raise fail(f"request {want_id} returned an error: {message['error']}")
            return message["result"]

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                         "clientInfo": {"name": "taxfill-bundle-probe", "version": "1"}}})
        server = receive(1).get("serverInfo", {})
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = sorted(t["name"] for t in receive(2).get("tools", []))
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    if listed != declared:
        missing, extra = sorted(set(declared) - set(listed)), sorted(set(listed) - set(declared))
        raise ProbeError(f"tools/list differs from manifest.json: missing {missing}, not declared {extra}")
    return {"server": server, "tools": listed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("bundle", type=Path, help="an unpacked .mcpb bundle (the directory holding manifest.json)")
    parser.add_argument("--timeout", type=float, default=600.0, help="seconds for the whole exchange (default 600)")
    args = parser.parse_args(argv)
    try:
        result = probe(args.bundle, args.timeout)
    except (ProbeError, OSError, ValueError) as exc:
        print(f"bundle_probe: FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"bundle_probe: OK: the server answered initialize (serverInfo {result['server']}) and listed "
          f"{len(result['tools'])} tools, exactly the manifest's")
    return 0


if __name__ == "__main__":
    sys.exit(main())
