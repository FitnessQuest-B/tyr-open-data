"""Write a NoCloud seed for the dedicated arm64 guest. No evaluator inputs."""

import argparse
import json
from pathlib import Path


SERVICE = """[Unit]
Description=TYR isolated benchmark supervisor
After=systemd-user-sessions.service user@1100.service
Wants=user@1100.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I /usr/local/lib/tyr-bootstrap.py
TimeoutStartSec=160

[Install]
WantedBy=multi-user.target
"""

BOOTSTRAP = """import json
import struct
import subprocess
import time
from pathlib import Path

control = Path('/dev/disk/by-id/virtio-tyr-control')
packet = Path('/dev/disk/by-id/virtio-tyr-input')
result = Path('/dev/virtio-ports/org.tyr.result')
deadline = time.monotonic() + 20
while not all(device.exists() for device in (control, packet, result)):
    if time.monotonic() >= deadline:
        if result.exists():
            header = json.dumps({"status": "environment_failure", "stage": "boot_readiness",
                                 "reason": "device_missing", "parts": [0, 0]}).encode()
            with result.open('wb') as port:
                port.write(b'TYR-RESULT/1\\n' + struct.pack('>I', len(header)) + header)
        subprocess.run(["systemctl", "poweroff", "--force", "--force"], check=True)
        raise SystemExit(1)
    time.sleep(0.1)
with control.open('rb') as stream:
    length, = struct.unpack('>I', stream.read(4))
    if not 0 < length <= 65536:
        raise RuntimeError('Invalid trusted supervisor size')
    code = stream.read(length)
    if len(code) != length:
        raise RuntimeError('Incomplete trusted supervisor')
exec(compile(code, '<verified-runner>', 'exec'), {'__name__': '__main__'})
"""

INSTALL = """#!/bin/sh
set -eu
trap 'echo TYR_PROVISION_FAILED >&2' EXIT
export DEBIAN_FRONTEND=noninteractive
sed -i 's|http://ports.ubuntu.com|https://ports.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
apt-get update
apt-get install -y --no-install-recommends podman uidmap dbus-user-session fuse-overlayfs python3
useradd -m -u 1100 tyrworker
loginctl enable-linger tyrworker
systemctl start user@1100.service
runuser -u tyrworker -- env XDG_RUNTIME_DIR=/run/user/1100 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1100/bus \\
    podman pull docker.io/library/python:3.12-slim
systemctl daemon-reload
systemctl enable tyr-isolation.service
apt-get clean
trap - EXIT
echo TYR_PROVISION_READY
systemctl poweroff
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(mode=0o700)
    files = [
        ("/usr/local/lib/tyr-bootstrap.py", BOOTSTRAP, "0644"),
        ("/etc/systemd/system/tyr-isolation.service", SERVICE, "0644"),
        ("/usr/local/sbin/tyr-provision", INSTALL, "0700"),
    ]
    config = {
        "hostname": "tyr-isolated-runner",
        "users": [],
        "ssh_pwauth": False,
        "disable_root": True,
        "write_files": [{"path": path, "content": content, "permissions": mode} for path, content, mode in files],
        "runcmd": [["/usr/local/sbin/tyr-provision"]],
    }
    (args.destination / "user-data").write_text("#cloud-config\n" + json.dumps(config) + "\n")
    (args.destination / "meta-data").write_text("instance-id: tyr-v020-runner\nlocal-hostname: tyr-isolated-runner\n")


if __name__ == "__main__":
    main()
