"""Provision the Local Jobs wrapper's private Python fallback and dashboard output."""

from functools import lru_cache
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import tempfile

from personal_package_files import physical_path, seal_directories, verify_file, verify_skill_tree

CANVAS = "canvases/local-jobs-dashboard.generated.canvas.tsx"
SIDECARS = ("canvases/local-jobs-dashboard.generated.canvas.data.json",
            "canvases/local-jobs-dashboard.canvas.data.json")


@lru_cache(maxsize=4)
def python_identity(command):
    """Resolve the host interpreter and minor version without loading site packages."""
    probe = "import sys,json; print(json.dumps([sys.executable, '%s.%s' % sys.version_info[:2]]))"
    try:
        raw = subprocess.check_output([command, "-ISB", "-c", probe],
                                      env={"PATH": os.defpath}, timeout=20, stderr=subprocess.PIPE)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Local Jobs needs a working system Python 3") from error
    executable, version = json.loads(raw)
    return Path(executable), version


def output_entries(directory, *, checkout):
    physical_path(directory / "canvases")
    names = []
    for name in (CANVAS, *SIDECARS) if checkout else (CANVAS,):
        path = directory / name
        if checkout and not os.path.lexists(path):
            continue
        info = path.lstat()
        modes = (0o600, 0o644) if checkout else (0o600,)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) not in modes):
            raise ValueError(f"Local Jobs requires a regular owner-controlled output at {path}")
        names.append(name)
    return names


def runtime_layout(dependency):
    executable, version = python_identity("/usr/bin/python3")
    cfg = f"home = {executable.parent}\ninclude-system-site-packages = false\n".encode()
    site = Path(".venv/lib") / ("python" + version) / "site-packages"
    files = {str(site / name): entry for name, entry in dependency["files"].items()}
    files[".venv/pyvenv.cfg"] = ("100644", len(cfg), hashlib.sha256(cfg).hexdigest())
    return executable, cfg, site, files


def provision(directory, dependency, archive):
    if len(archive) != dependency["length"] or hashlib.sha256(archive).hexdigest() != dependency["sha256"]:
        raise ValueError("Local Jobs received a different PyYAML source archive")
    executable, cfg, site, files = runtime_layout(dependency)
    root = directory / "_ops"
    binary = root / ".venv/bin/python3"
    binary.parent.mkdir(parents=True)
    binary.symlink_to(executable)
    config = root / ".venv/pyvenv.cfg"
    config.write_bytes(cfg)
    config.chmod(0o400)
    # Copy only named regular package sources and their license. No build or install script runs.
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for name in dependency["files"]:
            source = "LICENSE" if name == "PyYAML-LICENSE.txt" else "lib/" + name
            member = tar.getmember("pyyaml-6.0.3/" + source)
            if not member.isfile() or member.size != dependency["files"][name][1]:
                raise ValueError(f"unexpected PyYAML source member {name}")
            dest = root / site / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src:
                dest.write_bytes(src.read())
            dest.chmod(0o400)
    seal_directories(root, [*files, ".venv/bin/python3"])
    (directory / CANVAS).touch(mode=0o600, exist_ok=False)


def verify_python_cache(package, interpreter, version, sources):
    """Recompile pinned sources with the trusted interpreter, without importing the package."""
    cache = physical_path(package / "__pycache__")
    info = cache.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("unexpected Local Jobs bytecode cache directory")
    cached = {p.name: p for p in cache.iterdir()}
    tag = "cpython-" + version.removeprefix("python").replace(".", "")
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw).resolve()
        compiled = directory / package.relative_to(package.anchor)
        for suffix, flags in (("", []), (".opt-1", ["-O"]), (".opt-2", ["-OO"])):
            names = {source.stem + "." + tag + suffix + ".pyc": source for source in sources}
            selected = cached.keys() & names.keys()
            if not selected:
                continue
            try:
                subprocess.run([interpreter, "-ISB", *flags, "-X", "pycache_prefix=" + str(directory),
                                "-m", "py_compile", *(names[name] for name in sorted(selected))],
                               check=True, timeout=20, env={"PATH": os.defpath}, stderr=subprocess.PIPE)
            except (OSError, subprocess.SubprocessError) as error:
                raise ValueError("could not reproduce Local Jobs bytecode") from error
            for name in selected:
                path = cached.pop(name)
                info = path.lstat()
                if info.st_uid != os.getuid() or info.st_nlink != 1:
                    raise ValueError("unexpected Local Jobs bytecode ownership")
                expected = (compiled / name).read_bytes()
                verify_file(path, len(expected), hashlib.sha256(expected).hexdigest(),
                            (0o400, 0o444, 0o600, 0o644))
    if cached:
        raise ValueError("unexpected files in the Local Jobs bytecode cache")


def verify_independent(root, dependency):
    """Inspect the separately installed environment without starting its Python or loading job state."""
    env = physical_path(root / ".venv")
    config = env / "pyvenv.cfg"
    if not stat.S_ISREG(config.lstat().st_mode) or config.stat().st_size > 16384:
        raise ValueError("unexpected Local Jobs Python configuration")
    settings = {}
    for line in config.read_text().splitlines():
        key, sep, value = line.partition("=")
        if not sep or key.strip() in settings:
            raise ValueError("invalid Local Jobs Python configuration")
        settings[key.strip()] = value.strip()
    home = Path(settings.get("home", ""))
    if not home.is_absolute() or settings.get("include-system-site-packages") != "false":
        raise ValueError("Local Jobs requires an isolated Python installation")
    library = physical_path(env / "lib")
    sites = list(library.iterdir())
    if len(sites) != 1 or not re.fullmatch(r"python3\.[0-9]+", sites[0].name):
        raise ValueError("ambiguous Local Jobs Python version")
    version = sites[0].name
    site = physical_path(sites[0] / "site-packages")
    if any(p.suffix == ".pth" or p.name.split(".")[0] in {"sitecustomize", "usercustomize"}
           for p in site.iterdir()):
        raise ValueError("unexpected Python startup customization in the Local Jobs environment")
    executable = physical_path(env / "bin") / "python3"
    target = executable.resolve(strict=True)
    brew = Path("/opt/homebrew/opt") / version.replace("python", "python@") / "bin" / version
    bases = [python_identity("/usr/bin/python3")[0], Path(sys._base_executable), brew]
    if (not os.access(target, os.X_OK) or not any(base.is_file() and base.samefile(target) for base in bases)
            or not any((home / name).is_file() and (home / name).samefile(target)
                       for name in (version, "python3"))):
        raise ValueError("unrecognized independent Local Jobs Python interpreter")
    if "python" + python_identity(target)[1] != version:
        raise ValueError("Local Jobs' interpreter and site-packages versions differ")
    # The original installer used a wheel. A standalone source-only layout is also supported.
    package = physical_path(site / "yaml")
    names = {Path(name).name for name in dependency["files"] if name.startswith("yaml/")}
    for name in dependency["independent_native"]:
        native = package / Path(name).name
        if os.path.lexists(native):
            _, length, digest = dependency["independent_native"][name]
            verify_file(native, length, digest, (0o500, 0o700, 0o711, 0o755))
            names.add(native.name)
    cache = package / "__pycache__"
    if os.path.lexists(cache):
        names.add(cache.name)
    if {entry.name for entry in package.iterdir()} != names:
        raise ValueError("unexpected contents in the independent Local Jobs PyYAML package")
    for name, (_, length, digest) in dependency["files"].items():
        path = site / name
        if name == "PyYAML-LICENSE.txt" and not os.path.lexists(path):
            path = physical_path(site / "pyyaml-6.0.3.dist-info/licenses") / "LICENSE"
        verify_file(path, length, digest, (0o400, 0o444, 0o600, 0o644))
    if cache.name in names:
        sources = [site / name for name in dependency["files"] if name.endswith(".py")]
        verify_python_cache(package, target, version, sources)


def verify(directory, dependency, *, checkout):
    root = physical_path(directory / "_ops")
    if checkout:
        verify_independent(root, dependency)
        return
    executable, _, site, files = runtime_layout(dependency)
    verify_skill_tree(root, files, extra_entries=(".venv/bin/python3",))
    binary = root / ".venv/bin/python3"
    if not binary.is_symlink() or os.readlink(binary) != str(executable):
        raise ValueError("Local Jobs' Python link differs from the system interpreter")
    # Check the runtime after staging and again at its published location.
    probe = ('import sys,yaml; from pathlib import Path; '
             'sys.exit(Path(yaml.__file__).resolve() != Path(sys.argv[1]) or '
             'yaml.__version__ != "6.0.3" or yaml.safe_load("active: true") != {"active": True})')
    try:
        subprocess.run([binary, "-IB", "-c", probe, root / site / "yaml/__init__.py"],
                       env={"PATH": os.defpath}, check=True, timeout=20, stdout=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Local Jobs could not load the pinned PyYAML runtime") from error
