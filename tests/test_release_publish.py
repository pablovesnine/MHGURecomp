"""Offline publication policy tests. Header-only archives are NOT real releases.

Git, authenticated GitHub API, Docker and ELF symbol inspection are all mocked.
No command in this suite contacts GitHub or publishes the source/policy fixtures.
"""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SHA = "1" * 40
IMAGE = "sha256:" + "a" * 64
VERSION = "0.14.0"
NAME = "LinuxARM64-MHGURecomp." + VERSION + ".tar.gz"
TOP = "LinuxARM64-MHGURecomp"
REPO = "pablovesnine/MHGURecomp"


def load_publisher():
    spec = importlib.util.spec_from_file_location(
        "release_publish", ROOT / "tools/publish-linux-release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(data):
    return hashlib.sha256(data).hexdigest()


def elf():
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    header[16:18] = (3).to_bytes(2, "little")
    header[18:20] = (183).to_bytes(2, "little")
    header[20:24] = (1).to_bytes(4, "little")
    header[52:54] = (64).to_bytes(2, "little")
    return bytes(header)


class World:
    """Strict command/API simulator: unknown commands fail the test."""
    def __init__(self):
        self.commands = []
        self.writes = []
        self.dirty = ""
        self.branch = "master"
        self.head = self.master = SHA
        self.version = VERSION
        self.auth = True
        self.repository = REPO
        self.tag = None
        self.release = None
        self.asset_bytes = {}
        self.fail_upload = None
        self.corrupt_download = False
        self.manifest = {"schemaVersion": 2, "config": {"digest": IMAGE}}
        self.local_image_id = IMAGE
        self.local_os = "linux"
        self.local_arch = "amd64"
        self.labels = {"org.opencontainers.image.source":
                       "https://github.com/" + REPO,
                       "org.opencontainers.image.revision": SHA}
        self.run_info = dict(
            id=42, head_sha=SHA, head_branch="master", event="workflow_dispatch",
            path=".github/workflows/linux-ci.yml", status="completed",
            conclusion="success", head_repository={"full_name": REPO})
        self.jobs = [
            {"id": 1, "name": "validate / quick / quick", "conclusion": "success"},
            {"id": 2, "name": "validate / AArch64 without game data (amd64 host)",
             "conclusion": "success"},
            {"id": 3, "name": "publish / publish", "conclusion": "success"},
        ]
        self.statuses = []
        self.master_reads = 0
        self.master_changes_after = None
        self.manifest_reads = 0
        self.manifest_changes_after = None
        self.tag_lookup_hides_draft = False

    def run(self, args, **kwargs):
        self.commands.append(args)
        out = b""
        if args[0] == "git":
            command = args[1:]
            if command == ["rev-parse", "--show-toplevel"]:
                out = str(kwargs["cwd"]).encode()
            elif command == ["status", "--porcelain=v1", "--untracked-files=all"]:
                out = self.dirty.encode()
            elif command == ["symbolic-ref", "--quiet", "--short", "HEAD"]:
                out = self.branch.encode()
            elif command == ["rev-parse", "HEAD"]:
                out = self.head.encode()
            else:
                raise AssertionError(args)
        elif args[:2] == ["bash", str(ROOT / "tools/upstream-version.sh")]:
            out = self.version.encode()
        elif args[:2] == ["gh", "auth"]:
            if not self.auth:
                raise subprocess.CalledProcessError(1, args, stderr=b"not logged in")
        elif args[:2] == ["gh", "api"]:
            command = args[2:]
            assert command[:2] == ["--hostname", "github.com"], args
            command = command[2:]
            endpoint = command[0]
            method = command[command.index("--method") + 1] if "--method" in command else "GET"
            if endpoint.startswith("https://uploads.github.com/"):
                headers = [command[i + 1] for i, arg in enumerate(command)
                           if arg == "-H"]
                assert headers.count(
                    "Content-Length: " + str(len(kwargs["input"]))) == 1
            json_input = (kwargs.get("input") and "--input" in command and
                          command[-1] == "-" and not endpoint.startswith("https://uploads."))
            payload = json.loads(kwargs["input"]) if json_input else None
            try:
                value = self.api(endpoint, method, payload, kwargs.get("input"))
            except KeyError:
                raise subprocess.CalledProcessError(1, args, stderr=b"HTTP 404: Not Found")
            if isinstance(value, bytes):
                out = value
            else:
                if "--paginate" in command:
                    value = [value]
                out = json.dumps(value).encode()
        elif args[:3] == ["docker", "context", "inspect"]:
            out = b"unix:///fixture/docker.sock"
        elif args[:3] == ["docker", "buildx", "imagetools"]:
            self.manifest_reads += 1
            if self.manifest_changes_after and self.manifest_reads > self.manifest_changes_after:
                self.manifest["config"]["digest"] = "sha256:" + "d" * 64
            out = json.dumps(self.manifest).encode()
        elif args[:3] == ["docker", "--host", "unix:///fixture/docker.sock"]:
            command = args[3:]
            if command[:2] == ["image", "inspect"]:
                out = json.dumps([dict(Id=self.local_image_id, Os=self.local_os,
                                       Architecture=self.local_arch,
                                       Config={"Labels": self.labels})]).encode()
            elif command[0] == "run":
                assert "--network=none" in command and "--read-only" in command
                if command[command.index("--entrypoint") + 1] == "clang":
                    out = b"explicit header-only fixture\nadditional fixture compiler lines\n"
                else:
                    out = (f"{'b' * 64}  /opt/mhgu/host-packages.tsv\n"
                           f"{'c' * 64}  /opt/mhgu/arm64-packages.tsv\n").encode()
            else:
                raise AssertionError(args)
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, out, b"")

    def api(self, endpoint, method, payload, raw):
        prefix = "repos/" + REPO
        if method != "GET":
            self.writes.append((endpoint, method, payload))
        if endpoint == prefix:
            return {"full_name": self.repository, "default_branch": "master",
                    "permissions": {"push": True}}
        if endpoint == prefix + "/git/ref/heads/master":
            self.master_reads += 1
            if self.master_changes_after and self.master_reads > self.master_changes_after:
                self.master = "2" * 40
            return {"object": {"type": "commit", "sha": self.master}}
        if endpoint.startswith(prefix + "/actions/runs?"):
            return {"workflow_runs": [self.run_info]}
        if endpoint.startswith(prefix + "/commits/" + SHA + "/statuses"):
            return self.statuses
        if endpoint == prefix + "/actions/runs/42":
            return self.run_info
        if endpoint.startswith(prefix + "/actions/runs/42/jobs?"):
            return {"jobs": self.jobs}
        if endpoint == prefix + "/git/ref/tags/" + VERSION:
            if not self.tag:
                raise KeyError()
            return {"object": {"type": "commit", "sha": self.tag}}
        if endpoint == prefix + "/git/refs" and method == "POST":
            assert self.tag is None
            self.tag = payload["sha"]
            return {"object": {"type": "commit", "sha": self.tag}}
        if endpoint == prefix + "/releases/tags/" + VERSION:
            if not self.release or (self.tag_lookup_hides_draft and self.release["draft"]):
                raise KeyError()
            return copy.deepcopy(self.release)
        if endpoint == prefix + "/releases?per_page=100":
            return [copy.deepcopy(self.release)] if self.release else []
        if endpoint == prefix + "/releases" and method == "POST":
            assert self.tag == SHA
            self.release = dict(payload, id=7, assets=[])
            return copy.deepcopy(self.release)
        if endpoint == prefix + "/releases/7/assets?per_page=100":
            return copy.deepcopy(self.release["assets"])
        if endpoint.startswith("https://uploads.github.com/repos/" + REPO +
                               "/releases/7/assets?name="):
            name = endpoint.split("name=")[1]
            if self.fail_upload == name:
                raise subprocess.CalledProcessError(1, ["gh"], stderr=b"fixture upload failure")
            asset = dict(id=10 + len(self.release["assets"]), name=name,
                         size=len(raw), state="uploaded", digest="sha256:" + digest(raw))
            self.release["assets"].append(asset)
            self.asset_bytes[asset["id"]] = raw
            return asset
        if endpoint.startswith(prefix + "/releases/assets/"):
            data = self.asset_bytes[int(endpoint.rsplit("/", 1)[1])]
            return data + b"corrupt" if self.corrupt_download else data
        if endpoint == prefix + "/releases/7" and method == "PATCH":
            self.release.update(payload)
            return copy.deepcopy(self.release)
        raise AssertionError((endpoint, method, payload))


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.module = load_publisher()
        quiet = patch.object(self.module, "print", create=True)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / "dist"
        self.out.mkdir()
        self.world = World()
        self.metadata = dict(
            schema=1, platform="linux", architecture="aarch64", version=VERSION,
            source_revision=SHA, builder_image=IMAGE,
            tools={"compiler": "explicit header-only fixture",
                   "host_packages_sha256": "b" * 64,
                   "target_packages_sha256": "c" * 64},
            programs={name: digest(elf()) for name in ("mhgurecomp", "mhgugame.so")})
        self.entries = {
            "mhgurecomp": elf(), "mhgugame.so": elf(),
            "pipelines.list": b"explicit fixture",
            "data/putexefsromfsfoldershere.txt": self.module.dist.DATA_NOTE.encode(),
        }
        for name in self.module.dist.LICENSES:
            self.entries["licenses/" + name + ".txt"] = b"license fixture"
        self.write_archive()
        self.symbols = patch.object(self.module.dist, "check_arch")
        self.symbols.start()
        self.addCleanup(self.symbols.stop)

    def write_archive(self, extra=None):
        entries = dict(self.entries, **{"build-metadata.json":
                                      json.dumps(self.metadata).encode()})
        entries.update(extra or {})
        with tarfile.open(self.out / NAME, "w:gz") as stream:
            for name in ("", "data", "mods", "cheats", "bonus", "licenses"):
                entry = tarfile.TarInfo((TOP + "/" + name).rstrip("/"))
                entry.type = tarfile.DIRTYPE
                entry.mode = 0o755
                stream.addfile(entry)
            for name, content in entries.items():
                entry = tarfile.TarInfo(TOP + "/" + name)
                entry.size = len(content)
                entry.mode = 0o755 if name in ("mhgurecomp", "mhgugame.so") else 0o644
                stream.addfile(entry, io.BytesIO(content))
        self.checksums()

    def checksums(self):
        (self.out / "SHA256SUMS").write_text(
            digest((self.out / NAME).read_bytes()) + "  " + NAME + "\n")

    def legacy_body(self):
        receipt = {
            "source_revision": SHA, "builder_image": self.metadata["builder_image"],
            "assets": {name: digest((self.out / name).read_bytes())
                       for name in (NAME, "SHA256SUMS")},
        }
        return ("Linux ARM64 local release; no game data included.\n\n"
                "Local publisher receipt v1:\n" +
                json.dumps(receipt, sort_keys=True) + "\n")

    def publish(self, dry_run=False):
        return self.module.Publisher(ROOT, self.out, run=self.world.run).publish(dry_run)

    def rejected(self):
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            self.publish()
        self.assertEqual(self.world.writes, [])

    def test_dry_run_performs_all_preflights_without_writes(self):
        self.publish(True)
        self.assertFalse(self.world.writes)
        self.module.dist.check_arch.assert_called_once()
        self.assertTrue(any("imagetools" in c for c in self.world.commands))

    def test_config_and_manifest_identities_are_bound_to_the_same_image(self):
        for package_kind in ("config", "manifest"):
            for local_kind in ("config", "manifest"):
                with self.subTest(package=package_kind, local=local_kind):
                    self.world = World()
                    manifest_id = "sha256:" + digest(json.dumps(self.world.manifest).encode())
                    aliases = {"config": IMAGE, "manifest": manifest_id}
                    self.metadata["builder_image"] = aliases[package_kind]
                    self.world.local_image_id = aliases[local_kind]
                    self.write_archive()
                    self.publish(True)
                    self.assertEqual(self.world.writes, [])
                    # Provenance checks still inspect and run only the immutable
                    # package identifier, never a mutable registry tag.
                    runs = [c for c in self.world.commands
                            if c[:4] == ["docker", "--host", "unix:///fixture/docker.sock", "run"]]
                    self.assertEqual(len(runs), 2)
                    self.assertTrue(all(aliases[package_kind] in c for c in runs))

    def test_manifest_package_retries_are_identical_and_never_relabel_metadata(self):
        image = "sha256:" + digest(json.dumps(self.world.manifest).encode())
        self.metadata["builder_image"] = self.world.local_image_id = image
        self.write_archive()
        archive_hash = digest((self.out / NAME).read_bytes())
        self.publish()
        writes = len(self.world.writes)
        self.publish()
        self.assertEqual(len(self.world.writes), writes)
        self.assertEqual(digest((self.out / NAME).read_bytes()), archive_hash)
        self.assertEqual(self.metadata["builder_image"], image)
        receipt = json.loads(self.world.release["body"].split(
            "```json\n", 1)[1].split("\n```", 1)[0])
        self.assertEqual(receipt["builder_image"], image)

    def test_unrelated_local_image_and_non_host_platform_remain_rejected(self):
        for attribute, value in (("local_image_id", "sha256:" + "f" * 64),
                                 ("local_os", "windows"), ("local_arch", "arm64")):
            with self.subTest(attribute=attribute):
                self.world = World()
                setattr(self.world, attribute, value)
                self.rejected()

    def test_index_cannot_masquerade_as_a_direct_manifest(self):
        self.world.manifest["manifests"] = []
        self.metadata["builder_image"] = "sha256:" + digest(json.dumps(self.world.manifest).encode())
        self.write_archive()
        self.rejected()

    def test_manifest_identity_rechecks_and_rejects_registry_tag_changes(self):
        image = "sha256:" + digest(json.dumps(self.world.manifest).encode())
        self.metadata["builder_image"] = self.world.local_image_id = image
        self.write_archive()
        self.world.manifest_changes_after = 1
        self.rejected()

    def test_success_finalizes_only_after_verified_assets(self):
        self.publish()
        self.assertFalse(self.world.release["draft"])
        self.assertEqual(self.world.tag, SHA)
        self.assertEqual({a["name"] for a in self.world.release["assets"]},
                         {NAME, "SHA256SUMS"})
        self.assertEqual(self.world.writes[-1][1], "PATCH")

    def test_new_notes_are_readable_with_collapsed_exact_provenance(self):
        self.publish()
        body = self.world.release["body"]
        self.assertTrue(body.startswith("# Linux ARM64 " + VERSION + "\n\n"))
        self.assertIn("My Linux ARM64 package", body)
        self.assertIn("sha256sum --check SHA256SUMS", body)
        self.assertIn("your own **MHGU 1.4.0** dump", body)
        self.assertIn("Back up existing saves", body)
        self.assertIn("Game data is not included.", body)
        self.assertIn("blob/" + SHA + "/docs/BUILD-LINUX-ARM64.md", body)
        self.assertIn("blob/" + SHA + "/docs/SETTINGS_UI.md", body)
        self.assertEqual(body.count("<details>"), 1)
        self.assertEqual(body.count("</details>"), 1)
        self.assertNotIn("<details open", body)
        self.assertIn("<summary>Build provenance</summary>", body)
        self.assertNotIn("FPS", body)
        self.assertNotIn("Odin", body)
        provenance = body.split("```json\n", 1)[1].split("\n```", 1)[0]
        expected = json.loads(self.legacy_body().split("receipt v1:\n", 1)[1])
        self.assertEqual(json.loads(provenance), expected)
        self.assertEqual(provenance, json.dumps(expected, sort_keys=True, indent=2))

    def test_legacy_published_retry_is_read_only_and_keeps_notes(self):
        self.publish()
        legacy = self.world.release["body"] = self.legacy_body()
        writes = len(self.world.writes)
        self.publish()
        self.assertEqual(len(self.world.writes), writes)
        self.assertEqual(self.world.release["body"], legacy)

    def test_legacy_partial_draft_resumes_without_rewriting_notes(self):
        self.world.fail_upload = "SHA256SUMS"
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        legacy = self.world.release["body"] = self.legacy_body()
        first_asset_id = self.world.release["assets"][0]["id"]
        self.world.fail_upload = None
        self.publish()
        self.assertFalse(self.world.release["draft"])
        self.assertEqual(self.world.release["body"], legacy)
        self.assertEqual(self.world.release["assets"][0]["id"], first_asset_id)

    def test_renderer_returns_only_deterministic_new_and_exact_legacy_bodies(self):
        hashes = {name: digest((self.out / name).read_bytes())
                  for name in (NAME, "SHA256SUMS")}
        first = self.module.release_bodies(VERSION, SHA, IMAGE, hashes)
        second = self.module.release_bodies(VERSION, SHA, IMAGE, dict(reversed(
            list(hashes.items()))))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertEqual(first[1], self.legacy_body())
        self.assertNotEqual(first[0], first[1])
        self.publish()
        self.assertEqual(self.world.release["body"], first[0])

    def test_altered_notes_or_embedded_receipts_still_block_retries(self):
        self.publish()
        bodies = (self.world.release["body"], self.legacy_body())
        for body in bodies:
            changed_hash = digest((self.out / NAME).read_bytes())
            for changed in ("arbitrary notes\n" + body, body + "\nextra text",
                            body.replace(SHA, "2" * 40),
                            body.replace(IMAGE, "sha256:" + "c" * 64),
                            body.replace(changed_hash, "0" * 64)):
                with self.subTest(body=body[:20], changed=changed[:30]):
                    self.world.release["body"] = changed
                    self.world.writes.clear()
                    self.rejected()

    def test_changed_notes_during_draft_retry_block_before_upload(self):
        self.world.fail_upload = "SHA256SUMS"
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        self.world.fail_upload = None
        self.world.writes.clear()
        original = self.world.api
        reads = 0

        def changing(endpoint, method, payload, raw):
            nonlocal reads
            if endpoint == "repos/" + REPO + "/releases?per_page=100":
                reads += 1
                if reads > 1:
                    self.world.release["body"] += "\nunexpected edit"
            return original(endpoint, method, payload, raw)

        with patch.object(self.world, "api", side_effect=changing):
            self.rejected()
        self.assertTrue(self.world.release["draft"])
        self.assertEqual(len(self.world.release["assets"]), 1)

    def test_binary_uploads_declare_exact_content_length(self):
        self.publish()
        uploads = [c for c in self.world.commands
                   if any(a.startswith("https://uploads.github.com/") for a in c)]
        self.assertEqual(len(uploads), 2)
        for command in uploads:
            endpoint = next(a for a in command
                            if a.startswith("https://uploads.github.com/"))
            name = endpoint.split("?name=", 1)[1]
            self.assertIn("Content-Length: " + str((self.out / name).stat().st_size),
                          command)

    def test_failure_messages_identify_upload_and_http_without_secrets(self):
        secret = "never-print-this-token"
        command = ["gh", "api", "--hostname", "github.com",
                   "https://uploads.github.com/repos/" + REPO +
                   "/releases/7/assets?name=" + NAME, "--method", "POST"]
        for stderr, status in ((b"gh: Length Required (HTTP 411)", "HTTP 411"),
                               (b"gh: Forbidden (HTTP 403)", "HTTP 403"),
                               (b"connection lost", None)):
            with self.subTest(status=status):
                exc = subprocess.CalledProcessError(
                    1, command, output=secret.encode(),
                    stderr=stderr + b"\nAuthorization: Bearer " + secret.encode())
                message = self.module.command_failure(exc)
                self.assertIn("GitHub asset upload", message)
                self.assertNotIn(secret, message)
                self.assertNotIn("Authorization", message)
                if status:
                    self.assertIn(status, message)

    def test_no_auth_wrong_repository_dirty_branch_and_stale_sha(self):
        for attribute, value in (("auth", False), ("repository", "other/repo"),
                                 ("dirty", "?? private.txt\n"), ("branch", "feature"),
                                 ("master", "2" * 40), ("head", "bad")):
            with self.subTest(attribute=attribute):
                self.world = World()
                setattr(self.world, attribute, value)
                self.rejected()

    def test_wrong_version_and_0131_are_never_published(self):
        for version in ("0.13.1", "0.14.1", "v0.14.0", "0.14.0;echo"):
            with self.subTest(version=version):
                self.world.version = version
                self.rejected()

    def test_stale_metadata_and_program_hashes(self):
        for key, value in (("source_revision", "2" * 40), ("version", "9"),
                           ("schema", 2), ("architecture", "x86_64"),
                           ("builder_image", "builder:latest"),
                           ("programs", {"mhgurecomp": "f" * 64})):
            with self.subTest(key=key):
                original = self.metadata[key]
                self.metadata[key] = value
                self.write_archive()
                self.rejected()
                self.metadata[key] = original

    def test_wrong_elf_is_rejected_even_when_hashes_match(self):
        bad = bytearray(elf())
        bad[18:20] = (62).to_bytes(2, "little")
        self.entries["mhgugame.so"] = bytes(bad)
        self.metadata["programs"]["mhgugame.so"] = digest(bad)
        self.write_archive()
        self.rejected()

    def test_exact_layout_rejects_private_traversal_and_duplicate_entries(self):
        for extra in ("data/exefs/main", "../outside", "settings.ini",
                      "mhgurecomp-updater", "/absolute"):
            with self.subTest(extra=extra):
                self.write_archive({extra: b"must not ship"})
                self.rejected()
        self.write_archive()
        with tarfile.open(self.out / NAME) as stream:
            members = [(m, stream.extractfile(m).read() if m.isfile() else None)
                       for m in stream]
        with tarfile.open(self.out / NAME, "w:gz") as stream:
            for member, content in members + [members[-1]]:
                stream.addfile(member, io.BytesIO(content) if content is not None else None)
        self.checksums()
        self.rejected()

    def test_symlink_archive_entry_is_rejected(self):
        with tarfile.open(self.out / NAME) as stream:
            members = [(m, stream.extractfile(m).read() if m.isfile() else None)
                       for m in stream]
        members[-1][0].type = tarfile.SYMTYPE
        members[-1][0].linkname = "/private"
        members[-1][0].size = 0
        with tarfile.open(self.out / NAME, "w:gz") as stream:
            for member, content in members:
                stream.addfile(member, io.BytesIO(content) if member.isfile() else None)
        self.checksums()
        self.rejected()

    def test_checksum_stale_output_symlink_and_private_note_fail(self):
        (self.out / "SHA256SUMS").write_text("0" * 64 + "  " + NAME + "\n")
        self.rejected()
        self.checksums()
        stale = self.out / "old-release.tar.gz"
        stale.touch()
        self.rejected()
        stale.unlink()
        self.entries["data/putexefsromfsfoldershere.txt"] = b"private dump fixture"
        self.write_archive()
        self.rejected()
        (self.out / "SHA256SUMS").unlink()
        (self.out / "SHA256SUMS").symlink_to(self.out / NAME)
        self.rejected()

    def test_failed_missing_or_untrusted_full_checks_block(self):
        for key, value in (("conclusion", "failure"), ("head_sha", "2" * 40),
                           ("event", "pull_request"), ("head_branch", "feature"),
                           ("path", ".github/workflows/untrusted.yml"),
                           ("head_repository", {"full_name": "other/repo"})):
            with self.subTest(key=key):
                self.world = World()
                self.world.run_info[key] = value
                self.rejected()
        for index in range(3):
            self.world = World()
            self.world.jobs[index]["conclusion"] = "failure"
            self.rejected()
        self.world = World()
        self.world.jobs = self.world.jobs[:1]
        self.rejected()

    def test_sync_validation_requires_exact_success_status(self):
        self.world.run_info.update(path=".github/workflows/upstream-sync.yml",
                                   head_sha="2" * 40, event="schedule")
        self.rejected()
        self.world.statuses = [
            dict(context="upstream-sync/aarch64", state="success",
                 target_url="https://github.com/" + REPO + "/actions/runs/42")]
        self.publish(True)

    def test_wrong_ghcr_config_or_labels_or_package_provenance_block(self):
        self.world.manifest["config"]["digest"] = "sha256:" + "d" * 64
        self.rejected()
        for label in list(self.world.labels):
            self.world = World()
            self.world.labels[label] = "wrong"
            self.rejected()
        self.world = World()
        self.metadata["tools"]["target_packages_sha256"] = "f" * 64
        self.write_archive()
        self.rejected()

    def test_existing_different_tag_or_unowned_release_block(self):
        self.world.tag = "2" * 40
        self.rejected()
        self.world.tag = SHA
        self.world.release = dict(id=7, tag_name=VERSION, target_commitish=SHA,
                                  body="not this publisher", draft=True, assets=[])
        self.rejected()

    def test_partial_upload_leaves_draft_and_retry_never_replaces_assets(self):
        self.world.fail_upload = "SHA256SUMS"
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        self.assertTrue(self.world.release["draft"])
        self.assertEqual(len(self.world.release["assets"]), 1)
        original = self.world.release["assets"][0]["id"]
        self.world.fail_upload = None
        self.publish()
        self.assertFalse(self.world.release["draft"])
        self.assertEqual(self.world.release["assets"][0]["id"], original)
        self.assertEqual(sum(e.endswith("/git/refs") for e, _, _ in self.world.writes), 1)

    def test_different_asset_or_tampered_download_never_finalizes(self):
        self.world.fail_upload = "SHA256SUMS"
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        self.world.fail_upload = None
        self.world.release["assets"][0]["digest"] = "sha256:" + "0" * 64
        writes = len(self.world.writes)
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(len(self.world.writes), writes)
        self.assertTrue(self.world.release["draft"])

    def test_download_digest_is_independently_verified(self):
        self.world.corrupt_download = True
        with self.assertRaises(ValueError):
            self.publish()
        self.assertTrue(self.world.release["draft"])
        self.assertFalse(any(method == "PATCH" for _, method, _ in self.world.writes))

    def test_identical_published_retry_is_read_only(self):
        self.publish()
        writes = len(self.world.writes)
        self.publish()
        self.assertEqual(len(self.world.writes), writes)

    def test_abi_failure_blocks_before_remote_mutation(self):
        self.module.dist.check_arch.side_effect = ValueError("GLIBC_2.40")
        self.rejected()

    def test_retry_finds_drafts_even_when_published_tag_lookup_hides_them(self):
        self.world.fail_upload = "SHA256SUMS"
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        self.world.fail_upload = None
        self.world.tag_lookup_hides_draft = True
        self.publish()
        self.assertFalse(self.world.release["draft"])
        self.assertEqual(sum(endpoint == "repos/" + REPO + "/releases"
                             for endpoint, _, _ in self.world.writes), 1)

    def test_changed_local_hashes_cannot_resume_a_draft(self):
        self.world.fail_upload = "SHA256SUMS"
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        self.entries["pipelines.list"] = b"different fixture"
        self.write_archive()
        before = len(self.world.writes)
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(before, len(self.world.writes))

    def test_stale_master_or_retargeted_image_before_first_write_blocks(self):
        self.world.master_changes_after = 1
        self.rejected()
        self.world = World()
        self.world.manifest_changes_after = 1
        self.rejected()

    def test_master_change_after_draft_creation_leaves_recoverable_draft(self):
        # Initial master, guard, pre-tag guard, pre-draft guard, pre-upload guard.
        self.world.master_changes_after = 4
        with self.assertRaises(ValueError):
            self.publish()
        self.assertTrue(self.world.release["draft"])
        self.assertFalse(self.world.release["assets"])

    def test_extra_or_missing_digest_remote_assets_cannot_be_resumed(self):
        self.world.fail_upload = "SHA256SUMS"
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        self.world.fail_upload = None
        original = copy.deepcopy(self.world.release["assets"])
        for asset in (dict(original[0], name="private.txt"),
                      dict(original[0], digest=None)):
            self.world.release["assets"] = [asset]
            before = len(self.world.writes)
            with self.assertRaises(ValueError):
                self.publish()
            self.assertEqual(before, len(self.world.writes))

    def test_non_404_api_errors_never_allow_creating_replacement(self):
        original = self.world.api
        def failing(endpoint, method, payload, raw):
            if "/releases" in endpoint:
                raise subprocess.CalledProcessError(1, ["gh"], stderr=b"HTTP 503")
            return original(endpoint, method, payload, raw)
        with patch.object(self.world, "api", side_effect=failing):
            self.rejected()

    def test_metadata_unknown_fields_and_invalid_tools_are_rejected(self):
        for tools in ({}, {"compiler": "private\nlog"},
                      dict(self.metadata["tools"], unexpected="private"),
                      dict(self.metadata["tools"], compiler="wrong compiler fixture"),
                      dict(self.metadata["tools"], host_packages_sha256="bad")):
            original = self.metadata["tools"]
            self.metadata["tools"] = tools
            self.write_archive()
            self.rejected()
            self.metadata["tools"] = original
        self.metadata["private"] = "not permitted"
        self.write_archive()
        self.rejected()

    def test_ambiguous_or_boolean_metadata_schema_is_rejected(self):
        raw = json.dumps(self.metadata)
        raw = '{"source_revision": "private unexpected fixture", ' + raw[1:]
        self.write_archive({"build-metadata.json": raw.encode()})
        self.rejected()
        self.metadata["schema"] = True
        self.write_archive()
        self.rejected()

    def test_missing_member_permissions_and_trailing_payload_are_rejected(self):
        removed = self.entries.pop("licenses/LICENSE.txt")
        self.write_archive()
        self.rejected()
        self.entries["licenses/LICENSE.txt"] = removed
        self.write_archive()
        with tarfile.open(self.out / NAME) as stream:
            members = [(m, stream.extractfile(m).read() if m.isfile() else None)
                       for m in stream]
        members[-1][0].mode = 0o777
        with tarfile.open(self.out / NAME, "w:gz") as stream:
            for member, data in members:
                stream.addfile(member, io.BytesIO(data) if data is not None else None)
        self.checksums()
        self.rejected()
        self.write_archive()
        import gzip
        with gzip.open(self.out / NAME, "ab") as stream:
            stream.write(b"private trailing fixture")
        self.checksums()
        self.rejected()


class WrapperTests(unittest.TestCase):
    def test_default_interface_stays_offline_from_publisher(self):
        text = (ROOT / "tools/build-linux-release.sh").read_text()
        self.assertIn("publish=false", text)
        self.assertIn("--publish)", text)
        self.assertIn('if [[ $publish == true ]]', text)
        self.assertIn('umask 077', text)
        self.assertIn(':/game:ro,z', text)
        self.assertIn(':/out:Z', text)

    def test_check_and_publish_are_incompatible_before_git_or_docker(self):
        result = subprocess.run(
            ["bash", str(ROOT / "tools/build-linux-release.sh"),
             "--check", "--version", "0", "--publish"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--publish requires release mode", result.stderr)


class WrapperExecutionTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the established fake Docker/local Git fixture, not its tests.
        from test_linux_release import InterfaceTests
        self.fixture = InterfaceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        stub = f.repo / "tools/publish-linux-release.py"
        stub.write_text(
            '"""Records wrapper dispatch only; never publishes fixture files."""\n'
            'import json, os, sys\n'
            'from pathlib import Path\n'
            'Path(os.environ["PUBLISH_LOG"]).write_text(json.dumps(sys.argv[1:]))\n')
        f.git("add", "tools/publish-linux-release.py")
        f.git("-c", "user.name=Test Fixture", "-c", "user.email=fixture@example.invalid",
              "commit", "-qm", "Explicit publisher dispatch fixture")
        gh = f.bin / "gh"
        gh.write_text(
            '#!/bin/sh\n: > "$AUTH_LOG"\nexit "${AUTH_EXIT:-0}"\n')
        gh.chmod(0o755)
        f.env.update(PUBLISH_LOG=str(f.root / "publish.json"), AUTH_LOG=str(f.root / "auth"))

    def test_default_build_never_authenticates_or_calls_publisher(self):
        f = self.fixture
        result = f.release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(Path(f.env["AUTH_LOG"]).exists())
        self.assertFalse(Path(f.env["PUBLISH_LOG"]).exists())
        self.assertIn(str(f.repo / "dist") + ":/out:Z", f.run_command())

    def test_explicit_publish_uses_fresh_private_output_and_local_auth(self):
        f = self.fixture
        (f.repo / "dist").mkdir()
        (f.repo / "dist/stale-fixture").write_text("must never be published")
        result = f.release("--publish")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(Path(f.env["AUTH_LOG"]).exists())
        invocation = json.loads(Path(f.env["PUBLISH_LOG"]).read_text())
        self.assertEqual(invocation[0], "--dist")
        output = Path(invocation[1])
        self.assertEqual(output.parent, f.repo / ".linux-release")
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        self.assertIn(str(output) + ":/out:Z", f.run_command())
        self.assertFalse((output / "stale-fixture").exists())
        self.assertTrue((f.repo / "dist/stale-fixture").exists())

    def test_failed_build_never_calls_publisher(self):
        f = self.fixture
        f.env["ENGINE_EXIT"] = "23"
        self.assertEqual(f.release("--publish").returncode, 23)
        self.assertFalse(Path(f.env["PUBLISH_LOG"]).exists())

    def test_no_auth_stops_before_docker(self):
        f = self.fixture
        f.env["AUTH_EXIT"] = "1"
        result = f.release("--publish")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(f.log.exists())
        self.assertFalse(Path(f.env["PUBLISH_LOG"]).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
