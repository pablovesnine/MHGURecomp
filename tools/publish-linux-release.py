#!/usr/bin/env python3
"""Publish only a verified local ARM64 package, using existing gh authentication.

Run from a clean, current master checkout:
  python3 tools/publish-linux-release.py --dist dist --dry-run
  python3 tools/publish-linux-release.py --dist dist

Requires git, gh, local Docker/buildx and llvm-objdump. No dump is accessed.
Failures after creation deliberately retain the draft/tag for an identical retry.
Never updates/deletes tags or assets, and never touches release 0.13.1.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

REPOSITORY = "pablovesnine/MHGURecomp"
PREFIX = "repos/" + REPOSITORY
REGISTRY = "ghcr.io/pablovesnine/mhgurecomp-builder"
SHA = r"[0-9a-f]{40}"
DIGEST = r"sha256:[0-9a-f]{64}"
TOP = "LinuxARM64-MHGURecomp"
spec = importlib.util.spec_from_file_location(
    "release_dist", Path(__file__).with_name("dist.py"))
dist = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dist)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate build metadata key")
        result[key] = value
    return result


def image_identities(raw):
    """Bind either Docker storage identity to one exact registry manifest."""
    manifest = json.loads(raw)
    config = manifest.get("config", {}).get("digest")
    require(manifest.get("schemaVersion") == 2 and "manifests" not in manifest and
            isinstance(config, str) and re.fullmatch(DIGEST, config),
            "GHCR must provide a direct manifest with a pinned image config")
    # Classic Docker reports the config digest as .Id. Other image stores may
    # report the manifest digest. Both are immutable identities of this manifest,
    # not interchangeable arbitrary IDs or mutable source tags.
    return frozenset((config, "sha256:" + hashlib.sha256(raw).hexdigest()))


def command_failure(exc):
    """Describe the failed operation without exposing command/body credentials."""
    operation = Path(exc.cmd[0]).name
    if exc.cmd[:2] == ["gh", "api"]:
        operation = ("GitHub asset upload" if any(
            arg.startswith("https://uploads.github.com/") for arg in exc.cmd)
            else "GitHub API request")
    status = re.search(rb"\bHTTP ([1-5][0-9]{2})\b", exc.stderr or b"")
    detail = f"exit {exc.returncode}"
    if status:
        detail += "; HTTP " + status[1].decode("ascii")
    return f"{operation} failed ({detail})"


def release_bodies(version, revision, image, hashes):
    """Render readable notes and the exact legacy receipt for verified inputs."""
    receipt = {"source_revision": revision, "assets": hashes,
               "builder_image": image}
    legacy = ("Linux ARM64 local release; no game data included.\n\n"
              "Local publisher receipt v1:\n" +
              json.dumps(receipt, sort_keys=True) + "\n")
    source = "https://github.com/" + REPOSITORY + "/blob/" + revision
    notes = f"""# Linux ARM64 {version}

My Linux ARM64 package, based on stable [MHGURecomp {version}](https://github.com/morerokk/MHGURecomp/releases/tag/{version}).

## Install

1. Download `{TOP}.{version}.tar.gz` and `SHA256SUMS` into the same directory.
2. Verify the archive with `sha256sum --check SHA256SUMS`.
3. Extract it into a new directory on your ARM64 Linux device.
4. Copy `exefs/` and the complete `romfs/` from your own **MHGU 1.4.0** dump into `{TOP}/data/`.
5. Back up existing saves before upgrading, then run `./mhgurecomp` from the extracted directory.

ARM64 Linux only. Game data is not included.

See the [installation guide]({source}/docs/BUILD-LINUX-ARM64.md) and [settings guide]({source}/docs/SETTINGS_UI.md).

<details>
<summary>Build provenance</summary>

Local publisher receipt v1:

```json
{json.dumps(receipt, sort_keys=True, indent=2)}
```

</details>
"""
    return notes, legacy


class Publisher:
    def __init__(self, root, output, run=subprocess.run):
        self.root = Path(root).resolve()
        self.output = Path(output).absolute()
        self.run = run
        self.env = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1",
                        GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1")
        self.env.pop("GH_DEBUG", None)  # Never log authentication/upload bodies.

    def command(self, *args, data=None):
        return self.run(list(args), cwd=self.root, env=self.env, input=data,
                        capture_output=True, check=True).stdout

    def text(self, *args):
        return self.command(*args).decode().strip()

    def api(self, endpoint, method="GET", data=None, pages=False, optional=False):
        args = ["gh", "api", "--hostname", "github.com", endpoint,
                "--method", method]
        if pages:
            args += ["--paginate", "--slurp"]
        body = None
        if data is not None:
            args += ["--input", "-"]
            body = json.dumps(data).encode()
        try:
            return json.loads(self.command(*args, data=body))
        except subprocess.CalledProcessError as exc:
            # Authentication/network/permission failures must never mean "absent".
            if optional and re.search(rb"\bHTTP 404\b", exc.stderr or b""):
                return None
            raise

    def checkout(self):
        require(self.text("git", "rev-parse", "--show-toplevel") == str(self.root),
                "run from the repository root")
        require(self.text("git", "symbolic-ref", "--quiet", "--short", "HEAD") == "master",
                "publication requires master, not a branch or detached HEAD")
        require(not self.text("git", "status", "--porcelain=v1", "--untracked-files=all"),
                "publication requires a clean checkout (including untracked files)")
        revision = self.text("git", "rev-parse", "HEAD")
        require(re.fullmatch(SHA, revision), "expected a full source SHA")
        if hasattr(self, "revision"):
            require(revision == self.revision, "source changed during publication")
        return revision

    def current_master(self):
        self.checkout()
        ref = self.api(PREFIX + "/git/ref/heads/master")["object"]
        require(ref.get("type") == "commit" and ref.get("sha") == self.revision,
                "authenticated GitHub master does not match the local source")

    def local_package(self):
        require(not self.output.is_symlink() and self.output.is_dir(),
                "output must be a real directory")
        self.name = TOP + "." + self.version + ".tar.gz"
        require({p.name for p in self.output.iterdir()} == {self.name, "SHA256SUMS"},
                "output must contain exactly this archive and SHA256SUMS; no stale/private files")
        for name in (self.name, "SHA256SUMS"):
            dist.regular(self.output / name)
        archive_hash = dist.sha256(self.output / self.name)
        require((self.output / "SHA256SUMS").read_bytes() ==
                (archive_hash + "  " + self.name + "\n").encode(),
                "SHA256SUMS must contain the exact archive SHA-256 and filename")
        self.hashes = {name: dist.sha256(self.output / name)
                       for name in (self.name, "SHA256SUMS")}
        directories = {TOP + ("/" + n if n else "") for n in
                       ("", "data", "mods", "cheats", "bonus", "licenses")}
        files = set(dist.PROGRAMS) | {"pipelines.list", dist.METADATA,
                                     "data/putexefsromfsfoldershere.txt"}
        files |= {"licenses/" + n + ".txt" for n in dist.LICENSES}
        allowed = directories | {TOP + "/" + n for n in files}
        seen = set()
        # Never extract user-controlled names or links. Copy only fixed allowlist
        # files into a private 0700 temporary directory, with 0600 file modes.
        with tempfile.TemporaryDirectory(prefix="mhgu-release-") as temporary:
            build = Path(temporary)
            with tarfile.open(self.output / self.name, "r:gz") as archive:
                for member in archive:
                    require(member.name in allowed and member.name not in seen,
                            "archive has an unexpected or duplicate path")
                    seen.add(member.name)
                    directory = member.name in directories
                    require(member.type == (tarfile.DIRTYPE if directory else tarfile.REGTYPE) and
                            not member.linkname and not member.pax_headers and
                            member.uid == member.gid == 0 and
                            not member.uname and not member.gname,
                            "archive entry has unsafe type, owner or extended metadata")
                    executable = member.name in {TOP + "/" + n for n in dist.PROGRAMS}
                    require(member.mode == (0o755 if directory or executable else 0o644),
                            "archive entry has unexpected permissions")
                    if directory:
                        require(member.size == 0, "directory contains hidden payload")
                        continue
                    relative = member.name[len(TOP) + 1:]
                    if relative == dist.METADATA:
                        require(member.size <= 16384, "oversized build metadata")
                    target = build / relative
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with archive.extractfile(member) as source:
                        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        with os.fdopen(fd, "wb") as stream:
                            shutil.copyfileobj(source, stream, 1 << 20)
                require(seen == allowed, "archive is missing required files/directories")
                # tar readers normally ignore everything after the end marker.
                # Drain gzip as well: no appended archive/dump or gzip garbage.
                archive.fileobj.seek(archive.offset)
                for chunk in iter(lambda: archive.fileobj.read(1 << 20), b""):
                    require(not chunk.strip(b"\0"), "archive contains trailing hidden payload")
            require((build / "data/putexefsromfsfoldershere.txt").read_bytes() ==
                    dist.DATA_NOTE.encode(), "unexpected private/data placeholder content")
            with (build / dist.METADATA).open() as stream:
                metadata = json.load(stream, object_pairs_hook=unique_object)
            require(isinstance(metadata, dict) and set(metadata) == {
                "schema", "platform", "architecture", "version", "source_revision",
                "builder_image", "tools", "programs"}, "unsupported build metadata schema")
            require(type(metadata["schema"]) is int and metadata["schema"] == 1,
                    "unsupported build metadata schema number")
            self.image = metadata["builder_image"]
            dist.check_metadata(build, self.version, self.revision, self.image)
            tools = metadata["tools"]
            require(set(tools) == {"compiler", "host_packages_sha256", "target_packages_sha256"},
                    "missing or unexpected toolchain provenance")
            require(isinstance(tools["compiler"], str) and
                    0 < len(tools["compiler"]) <= 512 and
                    tools["compiler"].isascii() and tools["compiler"].isprintable(),
                    "invalid compiler provenance")
            for name in ("host_packages_sha256", "target_packages_sha256"):
                require(isinstance(tools[name], str) and
                        re.fullmatch(r"[0-9a-f]{64}", tools[name]),
                        "invalid package provenance digest")
            for name in dist.PROGRAMS:
                with (build / name).open("rb") as stream:
                    header = stream.read(64)
                require(len(header) == 64 and header[:7] == b"\x7fELF\x02\x01\x01" and
                        int.from_bytes(header[16:18], "little") in (2, 3) and
                        int.from_bytes(header[18:20], "little") == 183 and
                        header[20:24] == b"\x01\0\0\0" and header[52:54] == b"\x40\0",
                        "program is not ELF64 little-endian AArch64")
            dist.check_arch(build)  # Includes the existing GLIBC/GLIBCXX ceilings.
            self.tools = tools

    def validation(self):
        runs = [r for p in self.api(
            PREFIX + "/actions/runs?head_sha=" + self.revision + "&per_page=100", pages=True)
                for r in p["workflow_runs"]]
        statuses = [s for p in self.api(
            PREFIX + "/commits/" + self.revision + "/statuses?per_page=100", pages=True)
                    for s in p]
        # Sync runs start on the OLD master, then validate/promote the exact SHA.
        # Only the newest status for the dedicated context may authorize it.
        status = next((s for s in statuses if s["context"] == "upstream-sync/aarch64"), None)
        sync_id = None
        if status and status["state"] == "success":
            match = re.fullmatch("https://github.com/" + REPOSITORY +
                                r"/actions/runs/([1-9][0-9]*)", status.get("target_url", ""))
            if match:
                sync_id = int(match[1])
                runs.append(self.api(PREFIX + "/actions/runs/" + str(sync_id)))
        for run in runs:
            path = run.get("path")
            exact = ((path == ".github/workflows/linux-ci.yml" and
                      run.get("head_sha") == self.revision) or
                     (path == ".github/workflows/upstream-sync.yml" and
                      run.get("id") == sync_id))
            if not (exact and run.get("head_repository", {}).get("full_name") == REPOSITORY and
                    run.get("head_branch") == "master" and
                    run.get("event") in ("push", "schedule", "workflow_dispatch") and
                    run.get("status") == "completed" and run.get("conclusion") == "success"):
                continue
            jobs = [j for p in self.api(PREFIX + "/actions/runs/" + str(run["id"]) +
                                       "/jobs?per_page=100", pages=True) for j in p["jobs"]]
            required = ("AArch64 without game data (amd64 host)", "quick", "publish")
            if all(any(j["name"].split(" / ")[-1] == name and
                       j.get("conclusion") == "success" for j in jobs) for name in required):
                self.validation_run = run["id"]
                return
        raise ValueError("no successful full exact-source ARM64 validation and tools publication")

    def provenance(self):
        raw = self.command("docker", "buildx", "imagetools", "inspect",
                           REGISTRY + ":" + self.revision, "--raw")
        identities = image_identities(raw)
        require(self.image in identities,
                "GHCR manifest does not identify the attested tested image")
        self.manifest_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        context = self.env.get("DOCKER_CONTEXT")
        if context:
            endpoint = self.text("docker", "context", "inspect", context,
                                 "--format", "{{.Endpoints.docker.Host}}")
        else:
            endpoint = self.env.get("DOCKER_HOST") or self.text(
                "docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
        require(endpoint.startswith("unix://"), "select a local Docker socket")
        self.env.pop("DOCKER_HOST", None)
        self.env.pop("DOCKER_CONTEXT", None)
        self.docker = ["docker", "--host", endpoint]
        info = json.loads(self.command(*self.docker, "image", "inspect", self.image))[0]
        labels = info.get("Config", {}).get("Labels") or {}
        require(info.get("Id") in identities and info.get("Os") == "linux" and
                info.get("Architecture") == "amd64" and
                labels.get("org.opencontainers.image.revision") == self.revision and
                labels.get("org.opencontainers.image.source") == "https://github.com/" + REPOSITORY,
                "builder image lacks exact repository/source/platform provenance")
        # Only run the verified content-addressed public tools image; no mounts,
        # no daemon privileges, no dump, no network and no writable rootfs.
        sandbox = self.docker + [
            "run", "--rm", "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}"]
        sums = self.text(*sandbox, "--entrypoint", "sha256sum",
                         self.image, "/opt/mhgu/host-packages.tsv",
                         "/opt/mhgu/arm64-packages.tsv")
        expected = (self.tools["host_packages_sha256"] + "  /opt/mhgu/host-packages.tsv\n" +
                    self.tools["target_packages_sha256"] + "  /opt/mhgu/arm64-packages.tsv")
        require(sums == expected, "build metadata toolchain differs from verified GHCR image")
        compiler = self.text(*sandbox, "--entrypoint", "clang", self.image, "--version")
        require(compiler and compiler.splitlines()[0] == self.tools["compiler"],
                "build metadata compiler differs from verified GHCR image")

    def coordinates(self):
        tag = self.api(PREFIX + "/git/ref/tags/" + self.version, optional=True)
        if tag:
            require(tag["object"].get("type") == "commit" and
                    tag["object"].get("sha") == self.revision,
                    "existing tag differs; it will never be replaced")
        # The published-by-tag endpoint is not a reliable draft lookup. List
        # authenticated releases, including drafts, so a failed upload is resumable.
        releases = [r for p in self.api(PREFIX + "/releases?per_page=100", pages=True)
                    for r in p if r.get("tag_name") == self.version]
        require(len(releases) <= 1, "multiple releases use this tag; refusing publication")
        release = releases[0] if releases else None
        if release:
            require(tag is not None and release.get("tag_name") == self.version and
                    release.get("target_commitish") == self.revision and
                    release.get("body") in (self.body, self.legacy_body) and
                    not release.get("prerelease"),
                    "existing release is not this exact source and asset set")
        return tag, release

    def remote_assets(self, release, complete=False):
        assets = [a for p in self.api(PREFIX + "/releases/" + str(release["id"]) +
                                     "/assets?per_page=100", pages=True) for a in p]
        seen = set()
        for asset in assets:
            name = asset["name"]
            require(name in self.hashes and name not in seen,
                    "release contains an unexpected or duplicate asset")
            seen.add(name)
            path = self.output / name
            require(asset.get("state") == "uploaded" and asset.get("size") == path.stat().st_size and
                    asset.get("digest") == "sha256:" + self.hashes[name],
                    "existing asset differs; assets will never be replaced")
            data = self.command("gh", "api", "--hostname", "github.com",
                                PREFIX + "/releases/assets/" + str(asset["id"]),
                                "--method", "GET", "-H", "Accept: application/octet-stream")
            require(hashlib.sha256(data).hexdigest() == self.hashes[name],
                    "downloaded remote asset digest mismatch")
        require(not complete or seen == set(self.hashes), "release assets are incomplete")
        return seen

    def guard(self):
        self.current_master()
        for name, checksum in self.hashes.items():
            require(dist.sha256(dist.regular(self.output / name)) == checksum,
                    "local package changed during publication")
        manifest = self.command("docker", "buildx", "imagetools", "inspect",
                                REGISTRY + ":" + self.revision, "--raw")
        require("sha256:" + hashlib.sha256(manifest).hexdigest() == self.manifest_hash,
                "GHCR source tag changed during publication")
        return self.coordinates()

    def publish(self, dry_run=False):
        self.revision = self.checkout()
        self.command("gh", "auth", "status", "--hostname", "github.com")
        repository = self.api(PREFIX)
        require(repository.get("full_name") == REPOSITORY and
                repository.get("default_branch") == "master" and
                repository.get("permissions", {}).get("push") is True,
                "authentication must grant write access to the exact repository/master")
        self.current_master()
        self.version = self.text("bash", str(self.root / "tools/upstream-version.sh"))
        require(re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", self.version),
                "upstream verifier did not return a pinned numeric version")
        require(tuple(map(int, self.version.split("."))) != (0, 13, 1),
                "release 0.13.1 is preserved and cannot be published by this tool")
        self.local_package()
        self.validation()
        self.provenance()
        # Accept only complete canonical notes, never a receipt in arbitrary text.
        self.body, self.legacy_body = release_bodies(
            self.version, self.revision, self.image, self.hashes)
        tag, release = self.guard()
        present = self.remote_assets(release, complete=not release["draft"]) if release else set()
        if dry_run:
            print(f"publish: dry-run OK: {REPOSITORY} {self.version} {self.revision}")
            return
        if release and not release["draft"]:
            print("publish: identical release already published; no changes")
            return
        if not tag:
            self.guard()
            self.api(PREFIX + "/git/refs", "POST",
                     {"ref": "refs/tags/" + self.version, "sha": self.revision})
        if not release:
            _, raced_release = self.guard()
            require(raced_release is None, "release appeared during publication; retry safely")
            release = self.api(PREFIX + "/releases", "POST", {
                "tag_name": self.version, "target_commitish": self.revision,
                "name": "Linux ARM64 " + self.version, "body": self.body,
                "draft": True, "prerelease": False})
        for name in self.hashes:
            if name in present:
                continue
            _, current = self.guard()
            require(current and current["id"] == release["id"] and current["draft"],
                    "draft changed during publication; refusing upload")
            present = self.remote_assets(current)
            if name in present:
                continue
            body = (self.output / name).read_bytes()
            self.command("gh", "api", "--hostname", "github.com",
                         "https://uploads.github.com/" + PREFIX + "/releases/" +
                         str(release["id"]) + "/assets?name=" + name, "--method", "POST",
                         "-H", "Content-Type: application/octet-stream",
                         "-H", "Content-Length: " + str(len(body)), "--input", "-",
                         data=body)
        _, current = self.guard()
        require(current and current["id"] == release["id"] and current["draft"],
                "draft changed during publication; refusing finalize")
        self.remote_assets(current, complete=True)
        # Final external write, only after downloading and hashing BOTH assets.
        self.current_master()
        self.api(PREFIX + "/releases/" + str(release["id"]), "PATCH",
                 {"draft": False, "make_latest": "true"})
        print(f"publish: https://github.com/{REPOSITORY}/releases/tag/{self.version}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", default="dist", help="directory containing exactly tar + SHA256SUMS")
    parser.add_argument("--dry-run", action="store_true", help="all preflights, no GitHub writes")
    options = parser.parse_args()
    os.umask(0o077)
    try:
        Publisher(Path.cwd(), options.dist).publish(options.dry_run)
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError,
            subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            # Do not print captured gh/Docker output: it may contain credentials.
            message = command_failure(exc)
        else:
            message = str(exc)
        sys.exit("publish: " + message + "; any existing draft is retained for an identical retry")


if __name__ == "__main__":
    main()
