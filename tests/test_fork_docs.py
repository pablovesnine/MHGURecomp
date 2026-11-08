"""Validate maintained fork documentation without game data or network."""

from pathlib import Path
import configparser
import hashlib
import re
import subprocess
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    "README.md", "docs/BUILD-LINUX-ARM64.md",
    "docs/MAINTAINING.md", "docs/SETTINGS_UI.md", "docs/ENGINE-MODULES.md",
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


def linux_tab_labels(declaration):
    # Compare the Linux UI, not labels compiled only into another platform.
    compiled = subprocess.run(
        ["clang", "--target=aarch64-linux-gnu", "-E", "-P", "-x", "c++", "-"],
        input=declaration, text=True, capture_output=True, check=True,
    ).stdout
    return re.findall(r'"([^"]+)"', compiled)


class ForkDocumentationTests(unittest.TestCase):
    def test_0153_source_package_and_validation_boundaries(self):
        readme = (ROOT / "README.md").read_text()
        guide = (ROOT / "docs/SETTINGS_UI.md").read_text()
        maintaining = (ROOT / "docs/MAINTAINING.md").read_text()
        self.assertIn("targets upstream **0.15.3**", readme)
        self.assertIn("package remains **0.14.3**", readme)
        self.assertIn("/releases/tag/0.14.3", readme)
        for text in ("LoadingIndicator", "INI-only", "restart",
                     "Open the Forge menu", "Minus + Plus"):
            self.assertIn(text, guide)
        self.assertNotIn("Plus + B", guide + readme)
        for text in ("gen.id", "check-generated", "test-interp",
                     "test-villagehub", "--interp-ops",
                     "MHGU_TEST_FORGE_MENU", "villagehub.c"):
            self.assertIn(text, maintaining)
        self.assertIn("not measured", readme)
        for text in ("RyuServe", "RoomServe", "restart", "experimental",
                     "HP scaling", "passphrase"):
            self.assertIn(text, guide)
        self.assertIn("--network none", maintaining)
        self.assertIn("MHGU_TEST_MOUSE_CAPTURE", maintaining)
        for text in ("FixKerning", "BoldText", "HDRFormat", "SDR",
                     "Disable FSR and restart", "not tested HDR"):
            self.assertIn(text, guide)
        self.assertIn("test-textlayout", maintaining)
        for text in ("Direct connections", "public UDP address", "new links",
                     "20:00 UTC", "have not verified", "CGNAT", "0.15.3"):
            self.assertIn(text, guide)
        for text in ("test-ldn-direct", "test-villagehub-demo", "MHGU_TEST_DIRECT"):
            self.assertIn(text, maintaining)

    def test_tab_parser_preserves_all_linux_tabs_and_excludes_other_targets(self):
        declaration = (
            'const char *pages[] = {"Display"\n'
            '#ifdef __ANDROID__\n, "Android"\n#endif\n'
            '#ifdef _WIN32\n, "Windows"\n#endif\n'
            '#ifdef __linux__\n, "New Linux tab"\n#endif\n};'
        )
        self.assertEqual(linux_tab_labels(declaration), ["Display", "New Linux tab"])

    def test_save_folder_and_release_boundaries_are_documented(self):
        readme = (ROOT / "README.md").read_text()
        guide = (ROOT / "docs/SETTINGS_UI.md").read_text()
        maintaining = (ROOT / "docs/MAINTAINING.md").read_text()
        for text in ("SaveLocation", "save_0", "restart", "copy", "MHGU_SAVE_DIR"):
            self.assertIn(text, guide)
        for text in ("Choose folder", "Use the default folder", "Save and restart"):
            self.assertIn(text, guide)
        self.assertIn("MenuChord", guide)
        self.assertIn("0.13.1", readme.split("## Screenshots", 1)[1])
        self.assertIn("--publish", readme)
        self.assertIn("--dry-run", maintaining)
        self.assertNotIn("every six hours", readme + maintaining)

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
        runtime_tabs = linux_tab_labels(match.group(0) + ";")
        guide = (ROOT / "docs/SETTINGS_UI.md").read_text()
        documented_tabs = re.findall(r"^\| ([^|]+?) \|", guide, re.MULTILINE)
        documented_tabs = [tab for tab in documented_tabs if tab != "Tab" and not tab.startswith("-")]
        self.assertEqual(documented_tabs, runtime_tabs)

    def test_documented_repository_paths(self):
        # Validate paths mentioned in prose, not scripts/commands or hypothetical outputs.
        for relative in DOCUMENTS:
            text = (ROOT / relative).read_text()
            for path in re.findall(
                    r"`((?:\.github|docs|tools|runtime|updater|tests|extras)/[\w./-]+)`",
                    text):
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

    def test_custom_server_controls_match_runtime_and_documentation(self):
        config = (ROOT / "runtime/config.c").read_text()
        menu = (ROOT / "runtime/settings_panel.cpp").read_text()
        network = (ROOT / "runtime/net/ldn.c").read_text()
        guide = (ROOT / "docs/SETTINGS_UI.md").read_text()
        # The preparation commit keeps the old pin until the candidate passes.
        state = dict(line.split("\t", 1) for line in
                     (ROOT / ".github/maintenance/upstream-release.tsv")
                     .read_text().splitlines())
        live_network = tuple(map(int, state["version"].split("."))) >= (0, 14, 3)
        for key, label, restart in (
            ("Server", "Hub server", "false"),
            ("Key", "Matchmaking key", "false"),
            ("Join", "Search hosts", "false" if live_network else "true"),
            ("Port", "Host port (TCP / UDP)", "false" if live_network else "true"),
        ):
            with self.subTest(key=key):
                self.assertRegex(
                    config, rf'\{{"Multiplayer", "{key}",[^\n]*'
                    rf', {restart}, ERR_')
                self.assertIn(f'"{label}"', menu)
                self.assertIn(f"**{label}**", guide)
        hub_port = re.search(r"#define LOBBY_PORT (\d+)", network).group(1)
        self.assertIn(hub_port, guide)
        self.assertIn("39500", guide)
        self.assertIn("IPv4", guide)
        self.assertIn("## Custom hub server", guide)
        self.assertIn("**Save**", guide)

    def test_custom_server_example_does_not_claim_to_bundle_a_server(self):
        readme = (ROOT / "README.md").read_text()
        guide = (ROOT / "docs/SETTINGS_UI.md").read_text()
        example = re.search(r"```ini\n(\[Multiplayer\][^`]+)```", guide)
        self.assertIsNotNone(example)
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read_string(example.group(1))
        self.assertEqual(config.sections(), ["Multiplayer"])
        self.assertEqual(dict(config["Multiplayer"]), {
            "Server": "hub.example.org:39510",
            "Key": "my-private-group",
        })
        self.assertIn("Network > Hub server", readme)
        self.assertIn("not include a dedicated hub server", readme)
        self.assertIn(
            "https://github.com/morerokk/MHGURecomp/tree/"
            "51029aa1064c5cd1b7998e8479af82ddb15f91d3/server", guide)

    def test_0143_module_and_live_setting_boundaries(self):
        guide = (ROOT / "docs/ENGINE-MODULES.md").read_text()
        settings = (ROOT / "docs/SETTINGS_UI.md").read_text()
        for phrase in ("not a sandbox", "constructors", "enabled.txt",
                       "AArch64", "not include or enable"):
            self.assertIn(phrase, guide)
        self.assertNotIn("before any code", guide)
        self.assertIn("protocol 3", settings)
        self.assertIn("Sharpness and reactive mask apply on Save", settings)
        self.assertIn("close and reopen", settings)
        self.assertNotIn("All six need a restart", settings)

    def test_readme_distinguishes_features_from_unshipped_resources(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("empty `bonus/` directory", readme)
        self.assertIn("not include a bonus save", readme)
        self.assertIn("Updates", readme)
        self.assertIn("does not download or install updates", readme)
        self.assertNotIn("extras/cheats/", readme.replace("\\", "/"))
        self.assertNotRegex(readme, r"`[^`\n]*\\[^`\n]*`")

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
