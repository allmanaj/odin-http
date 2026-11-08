#!/usr/bin/env python3
"""Integration tests for graceful/forced server shutdown.

Builds tests/shutdown, starts it, then checks:
  1. A stuck handler cannot keep the process alive past the shutdown deadline.
  2. Idle keep-alive connections do not keep the process alive.

The listener port must be reusable after the process exits.
"""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEADLINE = 5.0
ALLOWANCE = 2.5  # build/startup noise + deadline


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build(out: Path) -> None:
    subprocess.run(
        ["odin", "build", str(ROOT / "tests" / "shutdown"), f"-out:{out}"],
        cwd=ROOT,
        check=True,
    )


def start_server(binary: Path, port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [str(binary)],
        env={**os.environ, "PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return proc
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError(f"server exited early:\n{proc.stdout.read()}")
            time.sleep(0.03)
    proc.kill()
    raise RuntimeError("server did not start")


def stop_and_wait(proc: subprocess.Popen, timeout: float) -> None:
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise AssertionError(f"server still alive {timeout}s after SIGINT")


def port_is_free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def test_stuck_handler(binary: Path) -> None:
    port = free_port()
    proc = start_server(binary, port)
    sock = socket.create_connection(("127.0.0.1", port), timeout=2)
    sock.sendall(b"GET /slow HTTP/1.1\r\nHost: localhost\r\n\r\n")
    time.sleep(0.3)  # let handler start
    stop_and_wait(proc, DEADLINE + ALLOWANCE)
    sock.close()
    assert port_is_free(port), "listener port still bound after forced exit"


def test_idle_keepalive(binary: Path) -> None:
    port = free_port()
    proc = start_server(binary, port)
    socks = []
    for _ in range(3):
        s = socket.create_connection(("127.0.0.1", port), timeout=2)
        s.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        s.recv(65536)
        socks.append(s)
    stop_and_wait(proc, 2.0)
    assert port_is_free(port), "listener port still bound after graceful exit"
    for s in socks:
        s.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        binary = Path(d) / "shutdown_test_server"
        build(binary)
        test_stuck_handler(binary)
        test_idle_keepalive(binary)
    print("ok")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
