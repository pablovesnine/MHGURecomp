"""Validate maintained fork documentation without game data or network."""

from pathlib import Path
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
        self.assertIn("update-build-arm64.sh", readme)
        self.assertLessEqual(len(readme.splitlines()), 70)
        self.assertIn("Docker", readme)
        self.assertIn("1.4.0", readme)
        self.assertIn("morerokk/MHGURecomp", readme)
        for platform in ("x86", "x64", "amd64", "windows", "android", "msys"):
            self.assertNotIn(platform, readme.lower())
        self.assertNotIn("BUILD-LINUX-MANUAL", readme)
        self.assertNotIn("BUILD-LINUX-DOCKER", readme)
        self.assertNotIn("mhgurecomp-updater.exe", readme)
        self.assertNotIn("Linux-MHGURecomp.0.13.0", readme)

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
