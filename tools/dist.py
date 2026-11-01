"""Package an attested Linux ARM64 Docker build; no private files or updater.

python tools/dist.py BUILD OUT linux VERSION --revision FULL_SHA --image sha256:ID
Internal post-make attestation:
python tools/dist.py record BUILD --version VERSION --revision FULL_SHA --image sha256:ID \
--compiler TEXT --host-packages FILE --target-packages FILE
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import time

PROGRAMS = ("mhgurecomp", "mhgugame.so")
METADATA = "build-metadata.json"
LICENSES = ("LICENSE", "THIRD_PARTY_NOTICES", "FFmpeg", "SDL3", "shaderc")
DATA_NOTE = ("Put your own dump of Monster Hunter Generations Ultimate 1.4.0 here: "
             "the exefs and romfs folders\n(data/exefs/main, data/romfs/...).\n")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_provenance(version, revision, image):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        raise ValueError("use a numeric release version")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("source revision must be a full Git SHA-1")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("builder image must be an immutable image ID")


def regular(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{path} is missing or not a regular build file")
    return path


def record_metadata(build, version, revision, image, tools):
    """Called by the container only after all required make targets succeed.

    Hashes bind the attestation to the exact successfully built programs.
    Existing metadata is invalidated by the entrypoint before it starts make.
    """
    validate_provenance(version, revision, image)
    if not isinstance(tools, dict) or not tools.get("compiler"):
        raise ValueError("compiler metadata is required")
    build = Path(build)
    data = dict(schema=1, platform="linux", architecture="aarch64",
                version=version, source_revision=revision, builder_image=image,
                tools=tools,
                programs={n: sha256(regular(build / n)) for n in PROGRAMS})
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=build, suffix=".part",
                                         delete=False, encoding="utf-8") as stream:
            temporary = stream.name
            json.dump(data, stream, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(temporary, build / METADATA)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def check_metadata(build, version, revision, image):
    validate_provenance(version, revision, image)
    build = Path(build)
    with regular(build / METADATA).open(encoding="utf-8") as stream:
        data = json.load(stream)
    expected = dict(schema=1, platform="linux", architecture="aarch64",
                    version=version, source_revision=revision, builder_image=image,
                    programs={n: sha256(regular(build / n)) for n in PROGRAMS})
    if not isinstance(data, dict) or any(data.get(k) != v for k, v in expected.items()):
        raise ValueError("build metadata does not match requested version/source/image/programs; rebuild")
    if not isinstance(data.get("tools"), dict) or not data["tools"].get("compiler"):
        raise ValueError("build metadata is missing compiler information")


def check_arch(build, arch="aarch64"):
    if arch != "aarch64":
        raise ValueError("only Linux aarch64 is supported")
    spec = importlib.util.spec_from_file_location(
        "release_check_elf", Path(__file__).parent / "docker/check-elf.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in PROGRAMS:
        module.check(Path(build) / name, arch)


def files(build, platform="linux"):
    """Allowlist only: no dump, save, updater, settings, log or cache."""
    if platform != "linux":
        sys.exit("dist: only Linux ARM64 is supported")
    build = Path(build)
    try:
        result = [(n, regular(build / n), True) for n in PROGRAMS]
        result += [(n, regular(build / n), False) for n in ("pipelines.list", METADATA)]
        for name in LICENSES:
            relative = "licenses/" + name + ".txt"
            result.append((relative, regular(build / relative), False))
        return result
    except ValueError as exc:
        sys.exit(f"dist: {exc} (make first)")


def package(build, out_dir, version, revision, image):
    check_metadata(build, version, revision, image)
    check_arch(build)
    entries = files(build)
    top = "LinuxARM64-MHGURecomp"
    name = f"{top}.{version}.tar.gz"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    now = int(time.time())

    def info(relative, size, mode, mtime, kind=tarfile.REGTYPE):
        entry = tarfile.TarInfo((top + "/" + relative).rstrip("/"))
        entry.size, entry.mode, entry.mtime, entry.type = size, mode, int(mtime), kind
        entry.uid = entry.gid = 0
        entry.uname = entry.gname = ""
        return entry

    temporary = None
    try:
        # Exclusive creation defeats pre-existing .part symlinks.
        with tempfile.NamedTemporaryFile(dir=out_dir, suffix=".part", delete=False) as stream:
            temporary = stream.name
        with tarfile.open(temporary, "w:gz", compresslevel=9, format=tarfile.GNU_FORMAT) as archive:
            for directory in ("", "data", "mods", "cheats", "bonus", "licenses"):
                archive.addfile(info(directory, 0, 0o755, now, tarfile.DIRTYPE))
            note = DATA_NOTE.encode()
            archive.addfile(info("data/putexefsromfsfoldershere.txt", len(note), 0o644, now),
                            io.BytesIO(note))
            for relative, source, executable in entries:
                with source.open("rb") as stream:
                    archive.addfile(info(relative, source.stat().st_size,
                                         0o755 if executable else 0o644,
                                         source.stat().st_mtime), stream)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    print(f"dist: {path}")
    print(f"      {path.stat().st_size} bytes, sha256:{sha256(path)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    record = len(sys.argv) > 1 and sys.argv[1] == "record"
    args = sys.argv[2:] if record else sys.argv[1:]
    parser.add_argument("build")
    if record:
        parser.add_argument("--version", required=True)
        parser.add_argument("--compiler", required=True)
        parser.add_argument("--host-packages", required=True)
        parser.add_argument("--target-packages", required=True)
    else:
        parser.add_argument("out")
        parser.add_argument("platform", choices=("linux",))
        parser.add_argument("version")
        parser.add_argument("--arch", choices=("aarch64",), default="aarch64")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--image", required=True)
    options = parser.parse_args(args)
    try:
        if record:
            tools = dict(compiler=options.compiler,
                         host_packages_sha256=sha256(regular(options.host_packages)),
                         target_packages_sha256=sha256(regular(options.target_packages)))
            record_metadata(options.build, options.version, options.revision, options.image, tools)
        else:
            package(options.build, options.out, options.version, options.revision, options.image)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        sys.exit(f"dist: {exc}")


if __name__ == "__main__":
    main()
