"""Bounded process and serial framing for the trusted host and guest supervisors."""

import hashlib
import json
import os
import selectors
import signal
import struct
import subprocess
import time

MAX_HEADER = 8192
MAX_RESULT = 96000
MAX_DIAGNOSTICS = 16384
READY = b"TYR-READY/1\n"
RESULT_START = b"TYR-RESULT/1\n"


def frame(fields, parts):
    header = dict(fields, parts=[len(part) for part in parts])
    data = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    if len(data) > MAX_HEADER:
        raise ValueError("Supervisor header exceeds its limit")
    return struct.pack(">I", len(data)) + data + b"".join(parts)


def receive(stream, limits):
    marker = stream.read(4)
    if len(marker) != 4:
        raise ValueError("Missing supervisor header")
    size, = struct.unpack(">I", marker)
    if not 0 < size <= MAX_HEADER:
        raise ValueError("Invalid supervisor header length")
    header = json.loads(stream.read(size))
    sizes = header.pop("parts")
    if len(sizes) != len(limits) or any(type(n) is not int or not 0 <= n <= limit
                                        for n, limit in zip(sizes, limits, strict=True)):
        raise ValueError("Unexpected supervisor payload length")
    parts = [stream.read(size) for size in sizes]
    if list(map(len, parts)) != sizes:
        raise ValueError("Incomplete supervisor payload")
    return header, parts


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def capture(command, timeout, sizes, *, deadline=None, **kwargs):
    """Return bounded output. Kill and reap the process group on limits."""
    started = time.monotonic()
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True, **kwargs)
    data = [bytearray(), bytearray()]
    status = "completed"

    def remaining():
        elapsed = time.monotonic() - started
        limit = timeout if deadline is None else min(timeout, deadline(data[0], elapsed))
        return max(0, limit - elapsed)

    try:
        with selectors.DefaultSelector() as selector:
            for index, stream in enumerate((child.stdout, child.stderr)):
                selector.register(stream, selectors.EVENT_READ, index)
            while selector.get_map():
                wait = remaining()
                if wait <= 0:
                    status = "timeout"
                    break
                for key, _ in selector.select(wait):
                    index = key.data
                    chunk = os.read(key.fd, min(16384, sizes[index] - len(data[index]) + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif len(data[index]) + len(chunk) > sizes[index]:
                        status = "output_limit"
                        break
                    else:
                        data[index].extend(chunk)
                if status != "completed":
                    break
            if status == "completed":
                try:
                    child.wait(timeout=remaining())
                except subprocess.TimeoutExpired:
                    status = "timeout"
    finally:
        if status != "completed" or child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        child.stdout.close()
        child.stderr.close()
    return status, child.returncode, bytes(data[0]), bytes(data[1]), round(1000 * (time.monotonic() - started))
