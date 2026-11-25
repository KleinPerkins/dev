"""Stage and verify the Skills index and its pinned parser for Personal Dev."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tarfile

from personal_package_files import seal_directories, verify_skill_tree


RELEASE = json.loads(Path(__file__).with_name("personal-index-runtime.json").read_bytes())


def package_files():
    return {**RELEASE["index_files"],
            **{"vendor/" + name: metadata for name, metadata in RELEASE["pyyaml"]["files"].items()}}


def verify(directory):
    verify_skill_tree(directory, package_files())


def stage(directory, read_url):
    source = ("https://raw.githubusercontent.com/KleinPerkins/skills/"
              f"{RELEASE['revision']}/global/tools/ecosystem-index")
    for name, (_, length, _) in RELEASE["index_files"].items():
        write_file(directory, name, read_url(f"{source}/{name}", length))

    parser = RELEASE["pyyaml"]
    archive = read_url(parser["archive"], parser["length"])
    if len(archive) != parser["length"] or sha256(archive).hexdigest() != parser["sha256"]:
        raise ValueError("Skills index received a different PyYAML source archive")
    with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as tar:
        for name, (_, length, _) in parser["files"].items():
            source = "LICENSE" if name == "PyYAML-LICENSE.txt" else "lib/" + name
            member = tar.getmember("pyyaml-6.0.3/" + source)
            if not member.isfile() or member.size != length:
                raise ValueError(f"unexpected PyYAML source member {name}")
            with tar.extractfile(member) as stream:
                write_file(directory, "vendor/" + name, stream.read())
    seal_directories(directory, package_files())


def write_file(directory, relative, payload):
    target = directory / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    target.chmod(0o400)


def index_digests():
    return {Path(name).name: metadata[2] for name, metadata in RELEASE["index_files"].items()}


def parser_digests():
    return {Path(name).name: metadata[2] for name, metadata in RELEASE["pyyaml"]["files"].items()
            if name.startswith("yaml/")}
