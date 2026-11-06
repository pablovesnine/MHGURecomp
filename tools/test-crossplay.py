#!/usr/bin/env python3
"""Supervise public protocol fixtures in an offline network namespace only."""
import argparse
from pathlib import Path
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from types import SimpleNamespace


def target_command(runner, binary, args):
    return [*runner, str(binary), *map(str, args)]


def require_isolated_network():
    if {name for _, name in socket.if_nameindex()} != {"lo"}:
        raise RuntimeError(
            "crossplay fixtures require an isolated network namespace "
            "(Docker --network none); refusing host/container networking")


class Harness:
    def __init__(self, directory, runner):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.children = []
        self.deadline = time.monotonic() + 180

    def __enter__(self):
        return self

    def start(self, name, command, target=True, env=None):
        path = self.directory / (name + ".log")
        output = path.open("w")
        try:
            # All concurrent fixtures belong to this foreground supervisor.
            # No daemon or detached work survives __exit__.
            process = subprocess.Popen(
                [*self.runner, *map(str, command)] if target else command,
                stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True, env=dict(os.environ, **(env or {})))
        except BaseException:
            output.close()
            raise
        child = SimpleNamespace(
            name=name, process=process, output=output, path=path)
        self.children.append(child)
        return child

    def wait_for(self, child, marker, timeout=30):
        deadline = min(self.deadline, time.monotonic() + timeout)
        while time.monotonic() < deadline:
            if child.process.poll() is not None:
                raise RuntimeError(f"{child.name} exited before readiness")
            if marker in child.path.read_text(errors="replace"):
                return
            time.sleep(0.05)
        raise RuntimeError(f"{child.name}: missing readiness {marker!r}")

    def finish(self, child, marker=None, timeout=70):
        remaining = min(timeout, self.deadline - time.monotonic())
        if remaining <= 0:
            raise RuntimeError("crossplay fixture deadline exceeded")
        status = child.process.wait(timeout=remaining)
        text = child.path.read_text(errors="replace")
        if status != 0:
            raise RuntimeError(f"{child.name}: exit {status}\n{text}")
        if "FAIL" in text:
            raise RuntimeError(f"{child.name}: FAIL marker\n{text}")
        if marker and marker not in text:
            raise RuntimeError(f"{child.name}: missing {marker!r}\n{text}")

    def alive(self, *servers):
        for server in servers:
            if server.process.poll() is not None:
                raise RuntimeError(f"{server.name} exited unexpectedly")

    def __exit__(self, *_):
        for child in reversed(self.children):
            if child.process.poll() is None:
                try:
                    os.killpg(child.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for child in reversed(self.children):
            try:
                child.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(child.process.pid, signal.SIGKILL)
                child.process.wait(timeout=3)
            finally:
                child.output.close()
        for child in self.children:
            print(f"--- {child.name}", flush=True)
            print(child.path.read_text(errors="replace"), flush=True)


def room_case(bins, runner, logs):
    with Harness(logs / "room", runner) as h:
        server = h.start("server", [bins / "test-room", "roomsrv", "24899", "", "150"])
        h.wait_for(server, "[server] up")
        a = h.start("a", [bins / "test-room", "a", "127.0.0.1:24899"])
        h.wait_for(a, "joined the room")
        b = h.start("b", [bins / "test-room", "b", "127.0.0.1:24899"])
        h.finish(b, "left the room")
        h.finish(a, "left the room")
        h.alive(server)
    print("crossplay room: OK", flush=True)


def ldn_case(bins, runner, logs, embedded):
    name = "ryusrv" if embedded else "ryuldn"
    with Harness(logs / name, runner) as h:
        port = "30497" if embedded else "30499"
        address = "127.0.0.1:" + port
        server = h.start(
            "server", [bins / "ryusrv-main", port, "150"]
            if embedded else [sys.executable, "-u", "tests/ryuldn_stub_server.py", port],
            target=embedded)
        h.wait_for(server, "listening on")
        host = h.start("host", [bins / "test-ryuldn", "host", address])
        h.wait_for(host, "host ready")
        join = h.start("join", [bins / "test-ryuldn", "join", address])
        h.finish(join, "left the lobby")
        h.finish(host, "lobby update after the join")
        h.alive(server)
    print(f"crossplay {name}: OK", flush=True)


def bridge_case(bins, runner, logs):
    with Harness(logs / "xbridge", runner) as h:
        ryu = h.start("ryu-server", [bins / "ryusrv-main", "30491", "150"])
        room = h.start(
            "room-server",
            [bins / "test-room", "roomsrv", "24891", "BridgeHost", "150"])
        h.wait_for(ryu, "listening on")
        h.wait_for(room, "[server] up")
        host = h.start(
            "host", [bins / "test-xbridge", "127.0.0.1:30491",
                     "127.0.0.1:24891", "60"])
        h.wait_for(host, "hub up")
        peer = h.start(
            "room-player", [bins / "emu-room", "join", "127.0.0.1:24891"],
            env={"EMU_HOLD": "20"})
        h.wait_for(host, "joined the hub on the server", timeout=30)
        h.wait_for(peer, "pong from the host", timeout=30)
        join = h.start(
            "ryu-player", [bins / "test-ryuldn", "join", "127.0.0.1:30491"])
        h.finish(join, "left the lobby")
        h.finish(host, "one room player bridged")
        h.finish(peer, "pong from the host")
        h.alive(ryu, room)
    print("crossplay xbridge: OK", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bins", required=True, type=Path)
    parser.add_argument("--runner", default="")
    args = parser.parse_args()
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    require_isolated_network()
    bins = args.bins.resolve()
    for name in ("test-room", "test-ryuldn", "test-xbridge", "emu-room", "ryusrv-main"):
        if not (bins / name).is_file():
            raise RuntimeError(f"missing required public fixture: {name}")
    runner = shlex.split(args.runner)
    logs = bins / "logs"
    room_case(bins, runner, logs)
    ldn_case(bins, runner, logs, embedded=False)
    ldn_case(bins, runner, logs, embedded=True)
    bridge_case(bins, runner, logs)
    print("crossplay public fixtures: ALL PASSED", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"crossplay public fixtures: FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
