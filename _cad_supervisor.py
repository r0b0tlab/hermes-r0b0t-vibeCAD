"""Private POSIX CAD supervisor, executed in a fresh interpreter.

The intermediate supervisor owns the group anchor, not Hermes. Only the live
anchor signals its own group, so an unrelated host waitpid(-1) cannot invalidate
its identity. This is lifecycle management, not a security sandbox.
"""
import json
import os
import selectors
import signal
import subprocess
import sys
import time


def send(fd, payload):
    data = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
    # Small atomic writes cannot fill the private status pipe before its reader
    # waits for the anchor. In particular, huge OS error paths cannot deadlock.
    if len(data) > 400:
        data = b'{"error":"CAD supervisor report too large"}\n'
    os.write(fd, data)


def anchor(control, status, timeout, argv):
    result = None
    try:
        try:
            child = subprocess.Popen(argv, close_fds=True)
        except OSError as exc:
            result = {"error": "could not start CAD subprocess: " + str(exc)}
        else:
            deadline = time.monotonic() + timeout
            with selectors.DefaultSelector() as selector:
                selector.register(control, selectors.EVENT_READ)
                while True:
                    code = child.poll()
                    if code is not None:
                        result = {"returncode": code}
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        result = {"timeout": True}
                        break
                    if selector.select(min(remaining, .02)) and not os.read(control, 1):
                        result = {"cancelled": True}
                        break
    except BaseException as exc:
        result = {"error": "CAD group anchor failed: " + repr(exc)}
    finally:
        # No process outside this session signals a numerical PGID. The anchor
        # is alive at the syscall, so its PID/PGID cannot have been reused.
        try:
            send(status, result or {"error": "missing anchor result"})
        finally:
            os.killpg(os.getpgrp(), signal.SIGKILL)
            os._exit(125)


def supervise(control, report, timeout, argv):
    read_status, write_status = os.pipe()
    try:
        worker = subprocess.Popen(
            [sys.executable, __file__, "anchor", str(control), str(write_status), str(timeout), *argv],
            pass_fds=(control, write_status), start_new_session=True,
        )
        os.close(write_status)
        write_status = -1
        # We are the anchor's only parent and have no external reaper here.
        worker.wait()
        with os.fdopen(read_status, "rb") as stream:
            read_status = -1
            raw = stream.readline(65536)
        if worker.returncode != -signal.SIGKILL:
            raise RuntimeError("CAD group anchor did not complete group cleanup")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("invalid anchor result")
        send(report, result)
    except BaseException as exc:
        send(report, {"error": "CAD supervision failed: " + repr(exc)})
    finally:
        if read_status >= 0:
            os.close(read_status)
        if write_status >= 0:
            os.close(write_status)


if __name__ == "__main__":
    # Ignored dispositions survive exec; inherited SIG_IGN would auto-reap
    # our children and invalidate the supervisor's exit-status protocol.
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    mode, control, output, timeout, *args = sys.argv[1:]
    if mode == "anchor":
        anchor(int(control), int(output), float(timeout), args)
    elif mode == "supervise":
        supervise(int(control), int(output), float(timeout), args)
    else:
        raise SystemExit("invalid CAD supervisor mode")
