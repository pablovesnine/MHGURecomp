"""Validate maintained fork documentation without game data or network."""

from pathlib import Path
import hashlib
import re
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    "README.md", "docs/BUILD-LINUX-ARM64.md",
    "docs/MAINTAINING.md", "docs/SETTINGS_UI.md",
)


def local_links(path):
    text = re.sub(r"```.*?```", "", path.read_text(), flags=re.DOTALL)
    for match in re.finditer(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", text):
        url = urlsplit(match.group(1))
        if not url.scheme and not url.netloc:
            yield url


def heading_anchors(path):
    anchors = set()
    counts = {}
    for line in path.read_text().splitlines():
        if not re.match(r"^#{1,6}\s+", line):
            continue
        heading = re.sub(r"^#{1,6}\s+", "", line)
        anchor = re.sub(r"[^\w\s-]", "", heading.lower()).replace(" ", "-")
        suffix = counts.get(anchor, 0)
        counts[anchor] = suffix + 1
        anchors.add(anchor + (f"-{suffix}" if suffix else ""))
    return anchors


class ForkDocumentationTests(unittest.TestCase):
    def test_reported_device_results_and_original_screenshots(self):
        readme = (ROOT / "README.md").read_text()
        for text in ("AYN Odin 3", "ArmadaOS 20261010", "120 FPS", "Eco",
                     "https://github.com/armada-os/armada", "morerokk"):
            self.assertIn(text, readme)
        self.assertRegex(readme, r"\bI (?:tested|test|have tested)\b")
        for name, digest in (
            ("gameplay", "505c83d8a6f33bf8f50aaa111a1564cc064ebc803bd1c1d042cd9623e196022d"),
            ("online", "05effb1b423f6f5557e6563a3324d2309ec2a02259ab7cdff7dff9557d5c6d86"),
            ("menu", "675e7119364c7dad9cdc33f1e634e9d4d84a0df4f52c620a8e31fd147b7cf083"),
        ):
            path = ROOT / f"docs/screenshots/ayn-odin3-{name}.jpg"
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            self.assertIn(str(path.relative_to(ROOT)), readme)

    def test_local_links_and_anchors(self):
        for relative in DOCUMENTS:
            document = ROOT / relative
            for link in local_links(document):
                with self.subTest(document=relative, link=link.geturl()):
                    target = document.parent / unquote(link.path) if link.path else document
                    self.assertTrue(target.exists(), f"Missing target: {target}")
                    if link.fragment and target.suffix == ".md":
                        self.assertIn(unquote(link.fragment), heading_anchors(target))

    def test_single_supported_build_entry(self):
        readme = (ROOT / "README.md").read_text()
        for text in ("pablovesnine/MHGURecomp.git", "bash tools/build-linux-release.sh",
                     '--game "$GAME_DIR"', "bash tools/upstream-version.sh",
                     "--jobs 2", "sha256sum --check SHA256SUMS", "git --version",
                     "docker info", "Linux x86-64", "Docker", "1.4.0",
                     "morerokk/MHGURecomp"):
            self.assertIn(text, readme)
        self.assertRegex(readme, r"https://github\.com/pablovesnine/MHGURecomp/releases(?:/tag/[0-9.]+)?\)")
        for text in ("BUILD_VERSION", "date -u", "x86-x64", "BUILD-LINUX-MANUAL",
                     "BUILD-LINUX-DOCKER", "mhgurecomp-updater.exe"):
            self.assertNotIn(text, readme)
        self.assertNotIn("--version", readme.replace("git --version", ""))
        build = readme.split("\n## Build\n", 1)[1].split("\n## ", 1)[0]
        for platform in ("windows", "android", "msys"):
            self.assertNotIn(platform, build.lower())
        maintaining = (ROOT / "docs/MAINTAINING.md").read_text()
        self.assertIn("git pull --ff-only origin master", maintaining)

    def test_settings_tabs_match_runtime(self):
        source = (ROOT / "runtime/settings_panel.cpp").read_text()
        match = re.search(r'const char \*pages\[\]\s*=\s*\{([^}]+)\}', source)
        self.assertIsNotNone(match, "Find the runtime tab labels")
        runtime_tabs = re.findall(r'"([^"]+)"', match.group(1))
        guide = (ROOT / "docs/SETTINGS_UI.md").read_text()
        documented_tabs = re.findall(r"^\| ([^|]+?) \|", guide, re.MULTILINE)
        documented_tabs = [tab for tab in documented_tabs if tab != "Tab" and not tab.startswith("-")]
        self.assertEqual(documented_tabs, runtime_tabs)

    def test_documented_repository_paths(self):
        # Validate paths mentioned in prose, not scripts/commands or hypothetical outputs.
        for relative in DOCUMENTS:
            text = (ROOT / relative).read_text()
            for path in re.findall(r"`((?:\.github|tools|runtime|updater|tests)/[\w./-]+)`", text):
                with self.subTest(document=relative, path=path):
                    self.assertTrue((ROOT / path).exists(), f"Stale documented path: {path}")
        maintaining = (ROOT / "docs/MAINTAINING.md").read_text()
        for name in ("sync-upstream.py", "fork-policy.json", "upstream-release.tsv"):
            self.assertIn(f".github/maintenance/{name}", maintaining)
            self.assertNotIn(f"`tools/{name}`", maintaining)
        for name in ("linux-ci.yml", "linux-checks.yml", "linux-builder.yml",
                     "linux-publisher.yml", "upstream-sync.yml"):
            self.assertIn(f".github/workflows/{name}", maintaining)
        self.assertNotIn("`tools/vkreplay.c`", maintaining)

    def test_bug_report_requests_package_and_source_provenance(self):
        template = (ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml").read_text()
        self.assertNotIn("0.13.0", template)
        self.assertIn("build-metadata.json", template)
        self.assertIn("revision", template)
        self.assertIn("git rev-parse HEAD", template)

    def test_public_documents_have_no_personal_script_or_home_paths(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                text = (ROOT / relative).read_text()
                self.assertNotIn("update-build-arm64", text)
                self.assertNotRegex(text, r"/home/[^/\s]+/")
                self.assertNotRegex(text, r"~/(?:MHGURecomp|[^/\s]+-test)")

    def test_public_author_voice_is_first_person(self):
        documents = (*DOCUMENTS, ".github/ISSUE_TEMPLATE/bug_report.yml")
        for relative in documents:
            with self.subTest(document=relative):
                text = (ROOT / relative).read_text()
                self.assertNotRegex(
                    text.lower(),
                    r"\b(?:maintainer|mantainer|maintainer-reported)\b")

    def test_prose_paragraphs_are_not_hard_wrapped(self):
        for relative in DOCUMENTS:
            previous_prose = False
            in_code = False
            for number, line in enumerate(
                    (ROOT / relative).read_text().splitlines(), start=1):
                if line.lstrip().startswith("```"):
                    in_code = not in_code
                    previous_prose = False
                    continue
                if in_code:
                    continue
                stripped = line.strip()
                is_prose = bool(stripped) and not re.match(
                    r"^(?:#{1,6}\s|\||[-+*]\s|\d+[.)]\s)", stripped)
                with self.subTest(document=relative, line=number):
                    self.assertFalse(
                        previous_prose and is_prose,
                        "Keep each prose paragraph on one source line")
                previous_prose = is_prose

    def test_personal_entry_points_are_not_public_files(self):
        self.assertEqual(list(ROOT.glob("update-build-arm64*.sh")), [])
        self.assertFalse((ROOT / "tests/test_update_build.py").exists())

    def test_notices_and_required_shared_sources_remain(self):
        for relative in (
            "LICENSE", "THIRD_PARTY_NOTICES", "runtime/platform/win_compat.h",
            "updater/updater.h", "updater/sha256.c",
            "tools/test_lift.py", "tools/test_harness.c",
        ):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())

    def test_removed_entry_points_are_not_documented_as_supported(self):
        for relative in (
            "android/android.mk", "android/apk.mk", "android/apk.py",
            "android/AndroidManifest.xml", "run-game.bat", "run-debug.bat",
            "docs/BUILD-LINUX-MANUAL.md", "docs/BUILD-LINUX-DOCKER.md",
            "runtime/platform/android.c", "runtime/platform/windows.c",
            "tools/bundle_dlls.py", "server", "extras/cheats",
            "updater/arch.h", "updater/archive.c", "updater/http.c",
            "updater/json.c", "updater/updater.c", "tests/test_update_arch.c",
            "docs/research", "docs/STATUS.md", "docs/FSR-PORT.md",
            "docs/SWITCH_COMPARE.md", "docs/PIPELINE_LIST.md",
        ):
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())


if __name__ == "__main__":
    unittest.main()
