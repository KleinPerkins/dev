"""Obtain a selected checkout binding from an owner-provided Codex connection."""

from dataclasses import dataclass
from hashlib import sha256
import json
import os
import re
import selectors
import time

from personal_checkout_inventory import Refused, lexical


MAX_REPLY_BYTES = 256 * 1024
IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,128}")


def selection_digest(project_id, checkout, thread_id=None):
    if thread_id is not None and (not isinstance(thread_id, str) or not IDENTIFIER.fullmatch(thread_id)):
        raise Refused("the linked checkout needs a valid Codex thread ID")
    identity = [project_id, checkout] if thread_id is None else [project_id, checkout, thread_id]
    selected = json.dumps(identity, ensure_ascii=True, separators=(",", ":"))
    return sha256(selected.encode()).hexdigest()


@dataclass(frozen=True)
class NativeProjectBinding:
    project_id: str
    checkout: str
    title: str | None
    updated_at: int | None
    observed_at: int
    thread_id: str | None = None

    @property
    def selection_digest(self):
        return selection_digest(self.project_id, self.checkout, self.thread_id)


def _selected_path(project_id, checkout):
    if not isinstance(project_id, str) or not IDENTIFIER.fullmatch(project_id):
        raise Refused("the selection needs an explicit Codex project ID")
    return lexical(checkout)


def read_desktop_project(catalog, project_id, checkout, *, observed_at):
    """Read a binding from the owning Desktop's current project tool result."""
    checkout = _selected_path(project_id, checkout)
    if (not isinstance(catalog, dict) or type(catalog.get("schemaVersion")) is not int
            or catalog["schemaVersion"] != 2
            or not isinstance(catalog.get("projects"), list)
            or type(observed_at) is not int or observed_at < 0):
        raise Refused("the Codex Desktop project tool did not return current catalog evidence")
    matches = [row for row in catalog["projects"] if isinstance(row, dict)
               and row.get("projectId") == project_id and row.get("hostId") == "local"]
    if len(matches) != 1:
        raise Refused("Codex Desktop did not identify one local project for the selected ID")
    row = matches[0]
    if row.get("projectKind") != "local" or row.get("isGitRepository") is not True:
        raise Refused("the selected Codex Desktop entry is not a local Git project")
    if lexical(row.get("path")) != checkout:
        raise Refused("the Codex Desktop project no longer binds the selected checkout")
    title = row.get("label")
    if title is not None and not isinstance(title, str):
        raise Refused("the Codex Desktop project returned invalid display evidence")
    return NativeProjectBinding(project_id, checkout, title, None, observed_at)


def read_desktop_linked_project(primary, linked_checkout, thread_id, membership, thread, *, observed_at):
    """Join Desktop project membership and the thread's exact checkout readback."""
    checkout = lexical(linked_checkout)
    if not isinstance(primary, NativeProjectBinding) or primary.thread_id is not None or checkout == primary.checkout:
        raise Refused("the linked checkout needs a separate registered primary project")
    if (not isinstance(thread_id, str) or not IDENTIFIER.fullmatch(thread_id)
            or type(observed_at) is not int or observed_at < primary.observed_at):
        raise Refused("the linked checkout needs current Codex thread evidence")
    if not isinstance(membership, dict) or membership.get("projectId") != primary.project_id:
        raise Refused("the Codex thread does not belong to the selected project")
    for row in (membership, thread):
        if (not isinstance(row, dict) or row.get("id") != thread_id
                or row.get("kind") != "codex" or row.get("hostId") != "local"):
            raise Refused("Codex did not confirm the same local thread on both reads")
        if lexical(row.get("cwd")) != checkout:
            raise Refused("Codex did not confirm the selected linked checkout on both reads")
    return NativeProjectBinding(primary.project_id, checkout, primary.title, None, observed_at, thread_id)


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate property")
        value[key] = item
    return value


def _wait(descriptor, event, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Refused("the Codex project read exceeded its deadline")
    with selectors.DefaultSelector() as selector:
        selector.register(descriptor, event)
        if not selector.select(remaining):
            raise Refused("the Codex project read exceeded its deadline")


class NativeProjectReader:
    """Read over a dedicated connection established by the installed native owner.

    The caller owns the connection and its authority. The public API reads
    project metadata through that existing connection.
    """

    def __init__(self, response, request):
        self.response = response
        self.request = request
        self.buffer = bytearray()
        self.next_id = 1
        self.initialized = False

    def _send(self, record, deadline):
        data = memoryview((json.dumps(record, separators=(",", ":")) + "\n").encode())
        while data:
            _wait(self.request, selectors.EVENT_WRITE, deadline)
            written = os.write(self.request, data)
            if not written:
                raise Refused("the Codex project connection closed before the request")
            data = data[written:]

    def _receive(self, request_id, deadline):
        received = len(self.buffer)
        while time.monotonic() < deadline:
            if b"\n" not in self.buffer:
                _wait(self.response, selectors.EVENT_READ, deadline)
                chunk = os.read(self.response, 65536)
                if not chunk:
                    raise Refused("the Codex project connection closed before the reply")
                received += len(chunk)
                if received > MAX_REPLY_BYTES:
                    raise Refused("the Codex project reply exceeded its byte limit")
                self.buffer.extend(chunk)
                continue
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer[:] = rest
            try:
                record = json.loads(line, object_pairs_hook=_object)
            except (UnicodeError, ValueError, RecursionError) as error:
                raise Refused("the Codex project connection returned an invalid reply") from error
            if not isinstance(record, dict):
                raise Refused("the Codex project connection returned an invalid reply")
            if "id" not in record and isinstance(record.get("method"), str):
                continue
            if type(record.get("id")) is not int or record["id"] != request_id or "method" in record:
                raise Refused("the Codex project connection returned an unexpected reply")
            if "error" in record or not isinstance(record.get("result"), dict):
                raise Refused("Codex could not supply the selected project")
            return record["result"]
        raise Refused("the Codex project read exceeded its deadline")

    def _call(self, method, params, deadline):
        request_id = self.next_id
        self.next_id += 1
        self._send({"id": request_id, "method": method, "params": params}, deadline)
        return self._receive(request_id, deadline)

    def read(self, project_id, checkout, *, deadline):
        checkout = _selected_path(project_id, checkout)
        try:
            if not self.initialized:
                params = {"clientInfo": {"name": "dev-checkout-authority", "version": "1"},
                          "capabilities": {"experimentalApi": True}}
                self._call("initialize", params, deadline)
                self._send({"method": "initialized", "params": {}}, deadline)
                self.initialized = True
            result = self._call("project/read", {"projectId": project_id}, deadline)
        except Refused:
            raise
        except (OSError, ValueError) as error:
            raise Refused("the owner-provided Codex project connection is unavailable") from error

        project = result.get("project")
        if not isinstance(project, dict) or project.get("id") != project_id:
            raise Refused("the Codex reply differs from the selected project ID")
        roots = project.get("roots")
        if not isinstance(roots, list) or any(not isinstance(root, dict) for root in roots):
            raise Refused("the Codex project has invalid root evidence")
        paths = [lexical(root.get("path")) for root in roots]
        if paths.count(checkout) != 1:
            raise Refused("Codex does not bind the selected checkout exactly once")
        title, updated = project.get("name"), project.get("updatedAt")
        if not isinstance(title, str) or type(updated) is not int or updated < 0:
            raise Refused("the Codex project has invalid display or revision evidence")
        return NativeProjectBinding(project_id, checkout, title, updated, int(time.time()))
