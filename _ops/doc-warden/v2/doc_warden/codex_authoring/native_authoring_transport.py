"""Bounded stdio lifetime for the source-pinned Codex authoring adapter.

The named-role owner validates native semantics. This layer only owns the
verified executable, channel, deadline and process cleanup.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

from ..canonical import digest_ref, parse_json_object


MAX_LINE = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 512 * 1024
MAX_NOTIFICATIONS = 32768
MAX_STREAM_BYTES = 64 * 1024 * 1024


class NativeAuthoringChannel:
    def __init__(self, *, binary: Path, binary_digest: str, cwd: Path,
                 configuration: tuple[str, ...], environment: dict[str, str]):
        binary = binary.resolve(strict=True)
        if not binary.is_file() or digest_ref(binary.read_bytes()) != binary_digest:
            raise ValueError("native_authoring_client_unqualified")
        self.binary = binary
        self.binary_digest = binary_digest
        self.cwd = cwd.resolve(strict=True)
        self.configuration = configuration
        self.environment = environment
        self.process = None
        self.selector = None
        self.pending = bytearray()
        self.sequence = 0
        self.observed = []
        self.notification_count = 0
        self.received_bytes = 0
        self.thread_notifications = set()
        self.reaped = False

    def __enter__(self):
        if self.process is not None:
            raise ValueError("native_authoring_channel_reused")
        self.process = subprocess.Popen(
            [str(self.binary), *self.configuration, "app-server", "--stdio"], cwd=self.cwd,
            env=self.environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            os.set_blocking(self.process.stdin.fileno(), False)
            self.selector = selectors.DefaultSelector()
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.process is None or self.reaped:
            return
        def signal_group(action):
            try:
                os.killpg(self.process.pid, action)
            except ProcessLookupError:
                return
            except PermissionError:
                # Darwin can report EPERM for an already exiting group.
                until = time.monotonic() + 0.25
                while time.monotonic() < until:
                    self.process.poll()
                    try:
                        os.killpg(self.process.pid, 0)
                    except ProcessLookupError:
                        return
                    except PermissionError:
                        pass
                    time.sleep(0.01)
                raise ValueError("native_authoring_process_cleanup_required") from None

        try:
            signal_group(signal.SIGTERM)
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            signal_group(signal.SIGKILL)
            self.process.wait(timeout=5)
            self.reaped = True
        finally:
            if self.selector is not None:
                self.selector.close()
            self.process.stdin.close()
            self.process.stdout.close()
        if not self.reaped:
            raise ValueError("native_authoring_process_cleanup_required")
        if digest_ref(self.binary.read_bytes()) != self.binary_digest:
            raise ValueError("native_authoring_client_changed")

    def _send(self, frame: dict, deadline: float):
        if self.process is None or self.process.poll() is not None:
            raise ValueError("native_authoring_channel_closed")
        raw = json.dumps(frame, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("native_authoring_request_too_large")
        pending = memoryview(raw + b"\n")
        fd = self.process.stdin.fileno()
        with selectors.DefaultSelector() as ready:
            ready.register(fd, selectors.EVENT_WRITE)
            while pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not ready.select(remaining):
                    raise ValueError("native_authoring_timeout")
                try:
                    pending = pending[os.write(fd, pending):]
                except BlockingIOError:
                    continue
                except OSError as exc:
                    raise ValueError("native_authoring_channel_closed") from exc

    def notify(self, method: str, deadline: float):
        self._send({"method": method}, deadline)

    def _receive(self, deadline: float) -> dict:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("native_authoring_timeout")
            end = self.pending.find(b"\n")
            if end >= 0:
                if end > MAX_LINE:
                    raise ValueError("native_authoring_protocol_line_too_large")
                raw = bytes(self.pending[:end])
                del self.pending[:end + 1]
                try:
                    return parse_json_object(raw)
                except (UnicodeError, ValueError) as exc:
                    raise ValueError("native_authoring_protocol_invalid") from exc
            if len(self.pending) > MAX_LINE:
                raise ValueError("native_authoring_protocol_line_too_large")
            if not self.selector.select(remaining):
                raise ValueError("native_authoring_timeout")
            block = os.read(self.process.stdout.fileno(), 64 * 1024)
            if not block:
                raise ValueError("native_authoring_channel_closed")
            self.received_bytes += len(block)
            if self.received_bytes > MAX_STREAM_BYTES:
                raise ValueError("native_authoring_stream_bound_exceeded")
            self.pending.extend(block)

    def _notification(self, frame: dict):
        method = frame.get("method")
        if "id" in frame or type(method) is not str:
            raise ValueError("native_authoring_unexpected_client_request")
        self.notification_count += 1
        if self.notification_count > MAX_NOTIFICATIONS:
            raise ValueError("native_authoring_event_bound_exceeded")
        # Preserve thread identity even for items whose content the decoder
        # doesn't use. Keep account metadata and command output out of evidence.
        payload = frame.get("params")
        if method == "thread/started":
            if not isinstance(payload, dict) or not isinstance(payload.get("thread"), dict):
                raise ValueError("native_authoring_protocol_invalid")
            self.observed.append({"method": method, "params": {"thread": {"id": payload["thread"].get("id")}}})
        elif method in ("item/completed", "turn/completed"):
            if not isinstance(payload, dict):
                raise ValueError("native_authoring_protocol_invalid")
            if method == "item/completed":
                item = payload.get("item")
                if not isinstance(item, dict):
                    raise ValueError("native_authoring_protocol_invalid")
                if item.get("type") not in ("subAgentActivity", "agentMessage"):
                    frame = {"method": method, "params": {
                        "threadId": payload.get("threadId"), "item": {"type": item.get("type")},
                    }}
            self.observed.append(frame)
        elif isinstance(payload, dict) and "threadId" in payload:
            thread = payload["threadId"]
            if not isinstance(thread, str) or len(thread) > 128:
                raise ValueError("native_authoring_protocol_invalid")
            # Streamed token deltas repeat the same thread. Carry foreign
            # thread evidence without retaining per-token metadata or text.
            if thread not in self.thread_notifications:
                self.thread_notifications.add(thread)
                self.observed.append({"method": method, "params": {"threadId": thread}})
        if len(self.observed) > 4096:
            raise ValueError("native_authoring_event_bound_exceeded")

    def request(self, method: str, params: dict, deadline: float) -> dict:
        self.sequence += 1
        self._send({"id": self.sequence, "method": method, "params": params}, deadline)
        while True:
            frame = self._receive(deadline)
            if type(frame.get("id")) is int and frame["id"] == self.sequence and "method" not in frame:
                if "error" in frame or not isinstance(frame.get("result"), dict):
                    raise ValueError("native_authoring_request_refused")
                return frame["result"]
            self._notification(frame)

    def wait_for_turn(self, thread_id: str, turn_id: str, deadline: float):
        while True:
            for frame in reversed(self.observed):
                if frame["method"] != "turn/completed":
                    continue
                params = frame["params"]
                if params.get("threadId") != thread_id:
                    continue
                turn = params.get("turn")
                if not isinstance(turn, dict) or turn.get("id") != turn_id or turn.get("status") != "completed":
                    raise ValueError("native_authoring_turn_incomplete")
                return
            self._notification(self._receive(deadline))
