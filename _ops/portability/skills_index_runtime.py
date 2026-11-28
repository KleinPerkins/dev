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
    def __init__(self, code, roots, release):
        self.code = code
        self.roots = roots
        self.release = release

    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] not in self.roots:
            return None
        if fullname not in self.code:
            raise ModuleNotFoundError("module is outside the paired Skills index", name=fullname)
        return spec_from_loader(fullname, self, is_package=fullname in self.roots)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(self.code[module.__name__], module.__dict__)


def _pinned_modules(root, directory, expected_digests, package):
    fd = child_directory(root, directory)
    try:
        code = {}
        for filename, digest in expected_digests.items():
            payload = read_regular(fd, filename)
            if sha256(payload).hexdigest() != digest:
                raise ValueError(f"the paired Skills index differs from its release pin: {filename}")
            name = package if filename == "__init__.py" else f"{package}.{filename[:-3]}"
            code[name] = compile(payload, f"<Skills {package}: {filename}>", "exec", dont_inherit=True)
        return code
    finally:
        os.close(fd)


def bind_index_runtime(package_root: Path, expected_digests: dict[str, str], *,
                       parser_digests: dict[str, str] | None = None, reuse=False) -> None:
    """Bind one verified Skills runtime before importing its modules.

    The released Dev profile supplies the installed path and the digest table
    from its qualified Skills release. Install media never supplies its own
    expected digests to this helper. A long-lived worker may reuse the same
    verified release and its own loaded modules.
    """
    if not sys.flags.isolated:
        raise ValueError("the paired Skills index needs an isolated Python worker")
    if (set(expected_digests) != set(INDEX_MODULE_FILES)
            or any(not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                   for digest in expected_digests.values())):
        raise ValueError("the paired Skills index needs a complete release pin")
    packages = {"lib"}
    if parser_digests is not None:
        if ("__init__.py" not in parser_digests
                or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*\.py", name)
                       or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                       for name, digest in parser_digests.items())):
            raise ValueError("the paired Skills index needs a valid parser release pin")
        packages.add("yaml")
    release = (package_root, frozenset(expected_digests.items()),
               frozenset(parser_digests.items()) if parser_digests is not None else None)
    loaded = {name: module for name, module in tuple(sys.modules.items())
              if name.partition(".")[0] in packages}
    bound = [finder for finder in sys.meta_path if isinstance(finder, _IndexModuleLoader)]
    if loaded or bound:
        if (reuse and len(bound) == 1 and bound[0].release == release
                and all(name in bound[0].code and getattr(module, "__loader__", None) is bound[0]
                        for name, module in loaded.items())):
            return
        raise ValueError("the Skills index namespace is already in use")

    root = absolute_directory(package_root)
    try:
        code = _pinned_modules(root, ("lib",), expected_digests, "lib")
        if parser_digests is not None:
            code.update(_pinned_modules(root, ("vendor", "yaml"), parser_digests, "yaml"))
    finally:
        os.close(root)
    sys.meta_path.insert(0, _IndexModuleLoader(code, packages, release))
