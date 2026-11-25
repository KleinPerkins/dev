"""Load the paired Skills index from the exact files selected by a Dev release."""

from hashlib import sha256
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_loader
import os
from pathlib import Path
import re
import sys

from personal_scope import absolute_directory, child_directory, read_regular


INDEX_MODULE_FILES = (
    "__init__.py",
    "adapters.py",
    "checkout_admission.py",
    "contracts.py",
    "deadline.py",
    "engine.py",
    "io_safe.py",
    "receipt_store.py",
)


class _IndexModuleLoader(MetaPathFinder, Loader):
    def __init__(self, code):
        self.code = code

    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] != "lib":
            return None
        if fullname not in self.code:
            raise ModuleNotFoundError("module is outside the paired Skills index", name=fullname)
        return spec_from_loader(fullname, self, is_package=fullname == "lib")

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(self.code[module.__name__], module.__dict__)


def bind_index_runtime(package_root: Path, expected_digests: dict[str, str]) -> None:
    """Bind one Skills runtime before imports in a fresh, isolated Dev worker.

    The released Dev profile supplies the installed path and the digest table
    from its qualified Skills release. Install media never supplies its own
    expected digests to this helper.
    """
    if not sys.flags.isolated:
        raise ValueError("the paired Skills index needs an isolated Python worker")
    if (set(expected_digests) != set(INDEX_MODULE_FILES)
            or any(not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                   for digest in expected_digests.values())):
        raise ValueError("the paired Skills index needs a complete release pin")
    if (any(name.partition(".")[0] == "lib" for name in sys.modules)
            or any(isinstance(finder, _IndexModuleLoader) for finder in sys.meta_path)):
        raise ValueError("the Skills index namespace is already in use")

    root = absolute_directory(package_root)
    try:
        lib = child_directory(root, ("lib",))
        try:
            payloads = {filename: read_regular(lib, filename) for filename in INDEX_MODULE_FILES}
        finally:
            os.close(lib)
    finally:
        os.close(root)

    for filename, payload in payloads.items():
        if sha256(payload).hexdigest() != expected_digests[filename]:
            raise ValueError(f"the paired Skills index differs from its release pin: {filename}")

    code = {}
    for filename, payload in payloads.items():
        name = "lib" if filename == "__init__.py" else f"lib.{filename[:-3]}"
        code[name] = compile(payload, f"<Skills index:{filename}>", "exec", dont_inherit=True)
    sys.meta_path.insert(0, _IndexModuleLoader(code))
