"""Validate maintained fork documentation without game data or network."""

from pathlib import Path
import hashlib
import re
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs/BUILD-LINUX-ARM64.md",
    ROOT / "docs/MAINTAINING.md",
)


def local_links(path):
    # Inline links are sufficient for these deliberately simple documents.
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
                     "https://github.com/armada-os/armada", "morerokk",
                     "previous maintainer build", "not yet device-tested"):
            self.assertIn(text, readme)
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
        for document in DOCUMENTS:
            for link in local_links(document):
                with self.subTest(document=document.name, link=link.geturl()):
                    target = document.parent / unquote(link.path) if link.path else document
                    self.assertTrue(target.exists(), f"Missing target: {target}")
                    if link.fragment and target.suffix == ".md":
                        self.assertIn(unquote(link.fragment), heading_anchors(target))

    def test_single_supported_build_entry(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("pablovesnine/MHGURecomp.git", readme)
        self.assertIn("bash tools/build-linux-release.sh", readme)
        self.assertIn('--game "$GAME_DIR"', readme)
        self.assertIn("bash tools/upstream-version.sh", readme)
        self.assertIn("--jobs 2", readme)
        self.assertNotIn("BUILD_VERSION", readme)
        self.assertNotIn("date -u", readme)
        self.assertNotIn("--version", readme.replace("git --version", ""))
        self.assertIn("sha256sum --check SHA256SUMS", readme)
        self.assertIn("git pull --ff-only origin master", readme)
        self.assertIn("git --version", readme)
        self.assertIn("docker info", readme)
        self.assertIn("Linux x86-64", readme)
        self.assertIn("https://github.com/pablovesnine/MHGURecomp/releases", readme)
        self.assertLessEqual(len(readme.splitlines()), 100)
        self.assertIn("Docker", readme)
        self.assertIn("1.4.0", readme)
        self.assertIn("morerokk/MHGURecomp", readme)
        for platform in ("windows", "android", "msys"):
            self.assertNotIn(platform, readme.lower())
        self.assertNotIn("BUILD-LINUX-MANUAL", readme)
        self.assertNotIn("BUILD-LINUX-DOCKER", readme)
        self.assertNotIn("mhgurecomp-updater.exe", readme)
        self.assertNotIn("Linux-MHGURecomp.0.13.0", readme)

    def test_public_documents_have_no_personal_script_or_home_paths(self):
        for document in DOCUMENTS:
            with self.subTest(document=document.name):
                text = document.read_text()
                self.assertNotIn("update-build-arm64", text)
                self.assertNotRegex(text, r"/home/[^/\s]+/")
                self.assertNotRegex(text, r"~/(?:MHGURecomp|[^/\s]+-test)")

    def test_personal_entry_points_are_not_public_files(self):
        self.assertEqual(list(ROOT.glob("update-build-arm64*.sh")), [])
        self.assertFalse((ROOT / "tests/test_update_build.py").exists())

    def test_notices_and_shared_sources_remain(self):
        for relative in (
            "LICENSE", "THIRD_PARTY_NOTICES",
            "runtime/platform/win_compat.h",
            "updater/updater.h", "updater/sha256.c",
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
