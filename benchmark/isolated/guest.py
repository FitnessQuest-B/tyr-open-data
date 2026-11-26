"""Trusted supervisor loaded by the guest boot service from the control disk."""

import io
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

# wire.py is prepended by the host and provides frame, receive and capture.
DEVICE = Path("/dev/disk/by-id/virtio-tyr-input")
RESULT = Path("/dev/virtio-ports/org.tyr.result")
WORKER = ["runuser", "-u", "tyrworker", "--", "env", "-i", "PATH=/usr/sbin:/usr/bin:/bin",
          "HOME=/home/tyrworker", "XDG_RUNTIME_DIR=/run/user/1100",
          "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1100/bus", "LC_ALL=C", "podman"]
CPU = 2
MEMORY = 2 * 1024**3
PROCESSES = 64
SCRATCH = 128 * 1024**2
CASE_SECONDS = 90


def podman(*args):
    return WORKER + list(args)


def checked(*args, timeout=15):
    status, code, data, log, _ = capture(podman(*args), timeout, (128000, MAX_DIAGNOSTICS))
    if status != "completed" or code != 0:
        raise RuntimeError(f"Podman {args[0]} failed ({status}, {code}): {log.decode(errors='replace')[-2000:]}")
    return data


def environment():
    if platform.system() != "Linux" or platform.machine() != "aarch64":
        raise RuntimeError("Expected an arm64 Linux guest")
    if set(os.listdir("/sys/class/net")) != {"lo"}:
        raise RuntimeError("Unexpected guest network interface")
    info = json.loads(checked("info", "--format=json"))
    host = info["host"]
    if (not host["security"]["rootless"] or not host["security"]["seccompEnabled"]
            or host["cgroupVersion"] != "v2" or host["cgroupManager"] != "systemd"
            or not {"memory", "cpu", "pids"} <= set(host["cgroupControllers"])):
        raise RuntimeError("The guest lacks the required rootless OCI controls")
    return {"kernel": platform.release(), "runtime": info["version"]["Version"],
            "cgroup_version": host["cgroupVersion"], "rootless": True}


def image_id(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
        value = "sha256:" + value
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError("Expected a pinned OCI image ID")
    return value


def configure(payload, scratch):
    context = scratch / "build"
    context.mkdir()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as source:
        source.extractall(context, filter="data")
    for entry in context.rglob("*"):
        entry.chmod(0o755 if entry.is_dir() else 0o644)
    checked("build", "--network=none", "--pull=never", "--tag", "localhost/tyr-reference:0.2",
            str(context), timeout=120)
    metadata = json.loads(checked("image", "inspect", "localhost/tyr-reference:0.2"))[0]
    return {"status": "configured", "image": image_id(metadata["Id"])}, b"", b""


def case(header, parts, scratch):
    image = image_id(header["image"])
    identifier = header["case"]
    if not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise ValueError("Invalid case ID")
    if [fingerprint(data) for data in parts] != header["sha256"]:
        raise ValueError("Staged packet hashes differ")
    metadata = json.loads(checked("image", "inspect", image))[0]
    if image_id(metadata["Id"]) != image or metadata["Architecture"] != "arm64":
        raise RuntimeError("Unexpected agent image identity or architecture")
    packet = scratch / identifier
    packet.mkdir(mode=0o755)
    for path, data in zip((packet / "task.json", packet / "records.sqlite", scratch / "contract.md"), parts,
                          strict=True):
        path.write_bytes(data)
        path.chmod(0o444)
    probe = header["probe"]
    command = podman(
        "run", "--rm", "--name=tyr-case", "--pull=never", "--network=none", "--read-only",
        "--read-only-tmpfs=false", "--user=65534:65534", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit", str(PROCESSES),
        "--memory", str(MEMORY), "--memory-swap", str(MEMORY), "--cpus", str(CPU),
        "--tmpfs", f"/tmp:rw,nodev,nosuid,size={SCRATCH},mode=1777", "--shm-size=1m",
        "--env=HOME=/tmp", "--env=TZ=UTC", "--env=LC_ALL=C", "--env=PYTHONDONTWRITEBYTECODE=1",
        "--http-proxy=false", "--image-volume=ignore", "--no-healthcheck", "--log-driver=none",
        "--mount", f"type=bind,source={packet},target=/packet/{identifier},ro",
        "--mount", f"type=bind,source={scratch / 'contract.md'},target=/contract.md,ro",
    )
    if probe is not None:
        if probe not in {"controls", "timeout", "overflow", "malformed"}:
            raise ValueError("Unknown public probe")
        (scratch / "private-sentinel").write_text("local public test sentinel")
        command += ["--entrypoint=/usr/local/bin/python3", image, "/app/benchmark/isolated/canary.py",
                    probe, f"/packet/{identifier}", str(scratch / "private-sentinel")]
    else:
        command += [image, f"/packet/{identifier}"]
    status, code, output, diagnostics, elapsed = capture(
        command, 3 if probe == "timeout" else CASE_SECONDS, (MAX_RESULT, MAX_DIAGNOSTICS)
    )
    if status != "completed":
        checked("rm", "--force", "--ignore", "tyr-case")
    remaining = [fingerprint(p.read_bytes()) for p in (packet / "task.json", packet / "records.sqlite", scratch / "contract.md")]
    if remaining != header["sha256"]:
        raise RuntimeError("Observation bytes changed")
    state = status if status != "completed" else "completed" if code == 0 else "agent_failure"
    receipt = {"status": state, "stage": "agent_execution", "exit_code": code, "elapsed_milliseconds": elapsed,
               "case_id": identifier, "image": image, "sha256": remaining,
               "limits": {"cpu": CPU, "memory": MEMORY, "pids": PROCESSES, "scratch": SCRATCH,
                          "seconds": 3 if probe == "timeout" else CASE_SECONDS}}
    return receipt, output, diagnostics


def main():
    with RESULT.open("wb") as port:
        stage = "boot_readiness"
        try:
            profile = environment()
            port.write(READY)
            port.flush()
            stage = "guest_execution"
            with tempfile.TemporaryDirectory(prefix="tyr-case-", dir="/run") as directory:
                scratch = Path(directory)
                scratch.chmod(0o755)
                with DEVICE.open("rb") as stream:
                    # One disk type per launch; the mode is chosen by the trusted host.
                    kind = stream.read(1)
                    if kind == b"B":
                        _, parts = receive(stream, (2 * 1024**2,))
                        answer, data, diagnostics = configure(parts[0], scratch)
                    elif kind == b"R":
                        header, parts = receive(stream, (8192, 16 * 1024**2, 16384))
                        answer, data, diagnostics = case(header, parts, scratch)
                    else:
                        raise ValueError("Unknown input disk format")
            payload = frame(dict(answer, guest=profile), [data, diagnostics])
        except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
            payload = frame({"status": "environment_failure", "stage": stage,
                             "reason": type(error).__name__}, [b"", b""])
        port.write(RESULT_START + payload)
    # The VM disk is disposable for cases. Sync setup writes before terminating
    # the guest so offline shutdown does not wait on unrelated cloud services.
    os.sync()
    subprocess.run(["systemctl", "poweroff", "--force", "--force"], check=True)


if __name__ == "__main__":
    main()
