"""Small harmless probes exercised only with public synthetic packets."""

import json
import os
import socket
import sys
import time
from pathlib import Path


def controls(packet, sentinel):
    packet = Path(packet)
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    assert os.getuid() == 65534 and int(status["CapEff"], 16) == 0
    assert status["NoNewPrivs"].strip() == "1" and status["Seccomp"].strip() == "2"
    cgroup = Path("/sys/fs/cgroup")
    assert (cgroup / "memory.max").read_text().strip() == str(2 * 1024**3)
    assert (cgroup / "pids.max").read_text().strip() == "64"
    quota, period = map(int, (cgroup / "cpu.max").read_text().split())
    assert quota == 2 * period
    assert set(os.listdir("/sys/class/net")) == {"lo"}
    assert os.statvfs("/").f_flag & os.ST_RDONLY
    assert os.statvfs(packet).f_flag & os.ST_RDONLY
    assert {child.name for child in packet.parent.iterdir()} == {packet.name}
    with socket.socket() as sock:
        sock.settimeout(0.5)
        assert sock.connect_ex(("192.0.2.1", 9)) != 0
    for target in (packet / "records.sqlite", packet / "unexpected", Path("/unexpected")):
        try:
            with target.open("ab"):
                raise AssertionError("Unexpected writable path")
        except OSError:
            pass
    for target in (Path(sentinel), Path("/dev/ttyAMA0"), Path("/run/podman/podman.sock"), Path("/var/run/docker.sock"),
                   Path("/packet-other"), Path("/home/tyrworker")):
        assert not target.exists(), str(target)
    assert not any(key in os.environ for key in ("SSH_AUTH_SOCK", "GH_TOKEN", "OPENAI_API_KEY"))
    assert (packet / "task.json").is_file() and Path("/contract.md").is_file()
    scratch = Path("/tmp/theres-a-canary")
    assert not scratch.exists()
    space = os.statvfs("/tmp")
    assert 0 < space.f_blocks * space.f_frsize <= 128 * 1024**2
    scratch.write_text("discard at exit")
    print(json.dumps({"status": "controls_passed"}, sort_keys=True))


if __name__ == "__main__":
    mode, packet, sentinel = sys.argv[1:]
    if mode == "controls":
        controls(packet, sentinel)
    elif mode == "timeout":
        time.sleep(30)
    elif mode == "overflow":
        print("x" * 96001)
    else:
        print("{}")
