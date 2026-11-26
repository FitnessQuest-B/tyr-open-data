"""Offline arm64 QEMU supervisor. Each case executes from a fresh disk overlay."""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "benchmark")]
import bench
import protocol
import scoring
from generate_synthetic import separated_roots
from wire import MAX_DIAGNOSTICS, MAX_HEADER, MAX_RESULT, READY, RESULT_START, capture, fingerprint, frame, receive

IMAGE = re.compile(r"sha256:[a-f0-9]{64}")
MAX_RECORDS = 16 * 1024**2
PROBES = {"controls": 2, "timeout": 1, "overflow": 1, "malformed": 1, "missing_result_device": 1}


class EnvironmentFailure(RuntimeError):
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__(f"Guest failure at {receipt['stage']} ({receipt['reason']})")


class GuestProgress:
    """Track trusted serial markers and deadlines without retaining payloads in receipts."""

    def __init__(self, configure=False):
        self.execution_seconds = 150 if configure else 115
        self.ready = self.delivery = self.complete = None

    def deadline(self, data, elapsed):
        offset = 0
        if data.startswith(READY):
            if self.ready is None:
                self.ready = elapsed
            offset = len(READY)
        if data.startswith(RESULT_START, offset):
            if self.delivery is None:
                self.delivery = elapsed
            if self.complete is None:
                stream = io.BytesIO(data[offset + len(RESULT_START):])
                try:
                    receive(stream, (MAX_RESULT, MAX_DIAGNOSTICS))
                except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
                    pass
                else:
                    self.complete = elapsed
        if self.complete is not None:
            return self.complete + 10
        if self.delivery is not None:
            return self.delivery + 8
        if self.ready is not None:
            return self.ready + self.execution_seconds
        return 35

    def telemetry(self):
        return {name + "_milliseconds": round(value * 1000) if value is not None else None
                for name, value in (("ready", self.ready), ("result_start", self.delivery),
                                    ("result_complete", self.complete))}

    @property
    def stage(self):
        if self.complete is not None:
            return "shutdown"
        if self.delivery is not None:
            return "result_delivery"
        return "guest_execution" if self.ready is not None else "boot_readiness"


def write_json(path, value):
    with open(path, "x", encoding="utf-8", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        stream.write(protocol.canonical(value) + "\n")


def limited(path, limit):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Input exceeds its byte limit")
    return data


def qemu_version(qemu):
    return subprocess.check_output([str(qemu), "--version"], text=True, timeout=10).splitlines()[0]


def options(path):
    return str(path).replace(",", ",,")


def control_source():
    return (HERE / "wire.py").read_bytes() + b"\n" + (HERE / "guest.py").read_bytes()


def launch_policy():
    return fingerprint(Path(__file__).read_bytes() + b"\n" + (HERE / "provision_guest.py").read_bytes())


def vm(disk, firmware, qemu, payload, *, configure=False, missing_result_device=False):
    control = control_source()
    with tempfile.TemporaryDirectory(prefix="tyr-arm64-") as tmp:
        scratch = Path(tmp)
        header = len(control).to_bytes(4, "big") + control
        for filename, data in (("control", header), ("input", payload)):
            (scratch / filename).write_bytes(data + bytes(-len(data) % 512))
        accelerator = "hvf" if sys.platform == "darwin" else "kvm"
        command = [
            str(qemu), "-machine", f"virt,accel={accelerator}", "-cpu", "host", "-m", "3072", "-smp", "2",
            "-nodefaults", "-no-reboot", "-display", "none", "-monitor", "none", "-serial", "none",
            "-nic", "none", "-bios", str(firmware),
            "-drive", f"if=virtio,format=qcow2,file={options(disk)}",
            "-drive", f"if=none,id=control,format=raw,readonly=on,file={options(scratch / 'control')}",
            "-device", "virtio-blk-pci,drive=control,serial=tyr-control",
            "-drive", f"if=none,id=packet,format=raw,readonly=on,file={options(scratch / 'input')}",
            "-device", "virtio-blk-pci,drive=packet,serial=tyr-input",
            "-chardev", "file,id=result,path=/dev/stdout",
            "-device", "virtio-serial-pci",
        ]
        if not missing_result_device:
            command += ["-device", "virtserialport,chardev=result,name=org.tyr.result"]
        if not configure:
            command.append("-snapshot")
        progress = GuestProgress(configure)
        status, code, raw, diagnostics, elapsed = capture(
            command, 205 if configure else 170,
            (MAX_HEADER + MAX_RESULT + MAX_DIAGNOSTICS + 4 + len(READY) + len(RESULT_START), MAX_DIAGNOSTICS),
            cwd=scratch, deadline=progress.deadline,
        )
        progress.deadline(raw, elapsed / 1000)
        measured = {"vm_elapsed_milliseconds": elapsed, "vm_exit_code": code, "vm_status": status,
                    "serial_bytes": len(raw), "vm_stderr_bytes": len(diagnostics), **progress.telemetry()}
        if status != "completed" or code != 0 or progress.complete is None:
            reason = status if status != "completed" else "guest_exit" if code != 0 else "incomplete_serial"
            raise EnvironmentFailure(dict(measured, stage=progress.stage, reason=reason))
        ready = raw.startswith(READY)
        stream = io.BytesIO(raw[(len(READY) if ready else 0) + len(RESULT_START):])
        try:
            result, parts = receive(stream, (MAX_RESULT, MAX_DIAGNOSTICS))
            if stream.read(1) or not isinstance(result.get("status"), str):
                raise ValueError("Unexpected result data")
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise EnvironmentFailure(dict(measured, stage="result_delivery", reason="invalid_serial")) from error
        if result["status"] == "environment_failure":
            raise EnvironmentFailure(dict(measured, stage=result["stage"], reason=result["reason"]))
        if not ready:
            raise EnvironmentFailure(dict(measured, stage="boot_readiness", reason="missing_ready_marker"))
        result.update(measured)
        return result, *parts


def worker_image_context():
    files = set(bench.WORKER_FILES) | {"benchmark/isolated/canary.py"}
    container = (
        b"FROM docker.io/library/python:3.12-slim\n"
        b"COPY app/ /app/\n"
        b'ENTRYPOINT ["/usr/local/bin/python3", "-B", "/app/benchmark/worker.py", "--worker", "drift-aware"]\n'
    )
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in [("Containerfile", container),
                           *[(f"app/{rel}", (ROOT / rel).read_bytes()) for rel in sorted(files)]]:
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(data), 0o644
            archive.addfile(entry, io.BytesIO(data))
    return stream.getvalue()


def configure(args):
    disk = args.profile.resolve().with_suffix(".qcow2")
    if disk.exists() or args.profile.exists():
        raise FileExistsError("Choose a new location for the frozen runner")
    image_context = worker_image_context()
    result, _, _ = vm(args.install_disk.resolve(), args.firmware.resolve(), args.qemu.resolve(),
                     b"B" + frame({}, [image_context]), configure=True)
    if result["status"] != "configured" or not IMAGE.fullmatch(result["image"]):
        raise RuntimeError("Reference image configuration failed")
    qemu_img = args.qemu.resolve().with_name("qemu-img")
    subprocess.run([str(qemu_img), "convert", "-O", "qcow2", str(args.install_disk), str(disk)],
                   check=True, timeout=180)
    disk.chmod(0o444)
    profile = {
        "version": 2, "image": result["image"], "guest": result["guest"],
        "disk": str(disk), "disk_sha256": protocol.hash_file(disk),
        "qemu": str(args.qemu.resolve()), "qemu_version": qemu_version(args.qemu),
        "firmware": str(args.firmware.resolve()), "firmware_sha256": protocol.hash_file(args.firmware),
        "build_context_sha256": fingerprint(image_context),
        "supervisor_sha256": fingerprint(control_source()),
        "launch_policy_sha256": launch_policy(),
    }
    write_json(args.profile, profile)
    return {"status": "configured", "image": profile["image"], "guest": profile["guest"]}


def load_profile(path):
    profile = protocol.read_json(path)
    protocol.fields(profile, "version image guest disk disk_sha256 qemu qemu_version "
                             "firmware firmware_sha256 build_context_sha256 supervisor_sha256 launch_policy_sha256")
    if (profile["version"] != 2 or not IMAGE.fullmatch(profile["image"])
            or protocol.hash_file(Path(profile["disk"])) != profile["disk_sha256"]
            or protocol.hash_file(Path(profile["firmware"])) != profile["firmware_sha256"]
            or fingerprint(control_source()) != profile["supervisor_sha256"]
            or launch_policy() != profile["launch_policy_sha256"]
            or qemu_version(Path(profile["qemu"])) != profile["qemu_version"]):
        raise ValueError("Runner profile fingerprints do not match")
    return profile


def packet_parts(packet, binding=None):
    task, source = protocol.read_packet(packet)
    raw = limited(packet / "task.json", 8192)
    records = limited(source, MAX_RECORDS)
    if protocol.digest(json.loads(raw)) != protocol.digest(task) or fingerprint(records) != task["source_sha256"]:
        raise ValueError("Packet changed during staging")
    if binding and (binding["task_sha256"] != protocol.digest(task) or binding["source_sha256"] != fingerprint(records)):
        raise ValueError("Packet differs from the private suite binding")
    return task, [raw, records, (ROOT / "benchmark/task.md").read_bytes()]


def run_one(profile, packet, *, binding=None, image=None, probe=None):
    task, parts = packet_parts(packet, binding)
    header = {"case": task["case_id"], "image": image or profile["image"], "probe": probe,
              "sha256": list(map(fingerprint, parts))}
    result, output, diagnostics = vm(Path(profile["disk"]), Path(profile["firmware"]), Path(profile["qemu"]),
                                     b"R" + frame(header, parts))
    if (result["guest"] != profile["guest"] or result["sha256"] != header["sha256"]
            or result["case_id"] != task["case_id"] or result["image"] != header["image"]):
        raise ValueError("Guest receipt does not bind to this case or profile")
    packet_parts(packet, binding)
    result["profile_sha256"] = protocol.digest(profile)
    return task, result, output, diagnostics


def result_submission(task, result, output):
    if result["status"] != "completed":
        return None
    try:
        value = scoring.submission(json.loads(output), task)
        if value["provider"] is not None:
            raise ValueError("External submissions cannot set provider accounting")
        return value
    except (ValueError, TypeError, KeyError, RecursionError):
        result["status"] = "invalid_submission"
        return None


def probe(args):
    profile = load_profile(args.profile)
    _, result, output, diagnostics = run_one(profile, args.packet)
    if result_submission(protocol.read_packet(args.packet)[0], result, output) is None:
        raise RuntimeError("The reference agent did not produce a valid submission: "
                           + diagnostics.decode(errors="replace")[-1500:])
    checks, telemetry = {}, {}
    for mode, expected in (("controls", "completed"), ("timeout", "timeout"),
                           ("overflow", "output_limit"), ("malformed", "invalid_submission"),
                           ("controls", "completed")):
        task, result, output, diagnostic = run_one(profile, args.packet, probe=mode)
        if mode == "controls" and result["status"] == "completed":
            assert json.loads(output) == {"status": "controls_passed"}
        if mode == "malformed":
            result_submission(task, result, output)
        if result["status"] != expected:
            raise RuntimeError(f"Public probe {mode} failed: {diagnostic.decode(errors='replace')[-1500:]}")
        if mode == "timeout":
            if result["stage"] != "agent_execution" or result["result_complete_milliseconds"] is None:
                raise RuntimeError("Agent timeout did not produce a complete guest receipt")
            telemetry[mode] = result
        checks[mode] = checks.get(mode, 0) + 1
    _, parts = packet_parts(args.packet)
    try:
        vm(Path(profile["disk"]), Path(profile["firmware"]), Path(profile["qemu"]),
           b"R" + frame({}, parts), missing_result_device=True)
    except EnvironmentFailure as error:
        if error.receipt["stage"] != "boot_readiness" or error.receipt["serial_bytes"] != 0:
            raise
        checks["missing_result_device"] = 1
        telemetry["missing_result_device"] = error.receipt
    if checks != PROBES:
        raise RuntimeError("The missing result device did not fail closed")
    report = {"profile_sha256": protocol.digest(profile), "checks": checks, "reference_submission": True,
              "telemetry": telemetry}
    write_json(args.output, report)
    return report


def run(args):
    profile = load_profile(args.profile)
    audit = protocol.read_json(args.probe, max_bytes=8192)
    if (audit.get("profile_sha256") != protocol.digest(profile) or audit.get("reference_submission") is not True
            or audit.get("checks") != PROBES):
        raise ValueError("Run the public isolation probes on this frozen profile first")
    indexed = protocol.read_json(args.index, max_bytes=2 * 1024**2)
    suite_audit = protocol.read_json(args.suite_audit)
    if (indexed.get("suite_version") != 3 or indexed.get("development") is not False
            or suite_audit.get("suite_version") != indexed["suite_version"]
            or suite_audit.get("passed") is not True
            or suite_audit.get("reassessment_coverage_passed") is not True
            or suite_audit.get("bindings_sha256") != protocol.digest(indexed["cases"])):
        raise ValueError("Use a frozen private suite manifest generated by the pilot")
    packet_root, output = separated_roots(args.agent_root, args.output)
    separated_roots(args.index.parent, output)
    case_ids = sorted(indexed["cases"])
    if len(case_ids) != 48 or set(case_ids) != {p.name for p in packet_root.iterdir()}:
        raise ValueError("The packet set differs from the frozen 48-case manifest")
    # Validate path layout and all bindings before starting any external process.
    for identifier in case_ids:
        packet_parts(packet_root / identifier, indexed["cases"][identifier])
    output.mkdir(mode=0o700)
    image = args.image or profile["image"]
    if not IMAGE.fullmatch(image):
        raise ValueError("Pin the agent by immutable OCI image ID")

    def batch(ids, destination):
        destination.mkdir(mode=0o700)

        def evaluate(identifier):
            packet = packet_root / identifier
            folder = destination / identifier
            folder.mkdir(mode=0o700)
            try:
                task, receipt, data, log = run_one(profile, packet, binding=indexed["cases"][identifier], image=image)
                value = result_submission(task, receipt, data)
                if value is not None:
                    write_json(folder / "submission.json", value)
                if log:
                    (folder / "diagnostics.log").write_bytes(log)
                    (folder / "diagnostics.log").chmod(0o600)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
                diagnostics = (error.receipt if isinstance(error, EnvironmentFailure) else
                               {"stage": "host_validation", "reason": type(error).__name__})
                receipt = {"case_id": identifier, "status": "environment_failure", "image": image,
                           "profile_sha256": protocol.digest(profile), **diagnostics}
            write_json(folder / "run.json", receipt)
            return receipt["status"]

        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            return list(pool.map(evaluate, ids))

    statuses = batch(case_ids, output / "first")
    repeats = case_ids[:args.repeat]
    replay_statuses = batch(repeats, output / "replay")
    if protocol.hash_file(Path(profile["disk"])) != profile["disk_sha256"]:
        raise RuntimeError("The immutable runner disk changed")
    return {"cases": len(statuses), "completed": statuses.count("completed"),
            "replays": len(replay_statuses), "completed_replays": replay_statuses.count("completed")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("configure")
    for name in ("install-disk", "firmware", "qemu", "profile"):
        command.add_argument("--" + name, required=True, type=Path)
    command = commands.add_parser("probe")
    for name in ("packet", "profile", "output"):
        command.add_argument("--" + name, required=True, type=Path)
    command = commands.add_parser("run")
    for name in ("agent-root", "index", "profile", "probe", "suite-audit", "output"):
        command.add_argument("--" + name, required=True, type=Path)
    command.add_argument("--image")
    command.add_argument("--jobs", type=int, choices=range(1, 5), default=1)
    command.add_argument("--repeat", type=int, choices=range(1, 9), default=6)
    args = parser.parse_args()
    try:
        print(json.dumps({"configure": configure, "probe": probe, "run": run}[args.command](args), sort_keys=True))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
