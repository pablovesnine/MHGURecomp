"""Bounded, checksum-verified source retrieval with offline fake curl."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = b"public source-download test fixture\n"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


class SourceFetchTests(unittest.TestCase):
    def invoke(self, mode, urls=("https://primary.test/source", "https://mirror.test/source"),
               digest=DIGEST):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / "curl"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json,os,pathlib,sys\n"
                "args=sys.argv[1:]\n"
                "log=pathlib.Path(os.environ['FETCH_LOG'])\n"
                "records=json.loads(log.read_text()) if log.exists() else []\n"
                "records.append(args)\n"
                "log.write_text(json.dumps(records))\n"
                "target=pathlib.Path(args[args.index('--output')+1])\n"
                "mode=os.environ['FETCH_MODE']\n"
                "target.write_bytes(b'partial')\n"
                "if mode=='offline' or (mode=='fallback' and len(records)==1): sys.exit(28)\n"
                "target.write_bytes(b'bad' if mode=='corrupt' else "
                + repr(PAYLOAD) + ")\n"
            )
            fake.chmod(0o755)
            result = subprocess.run(
                ["bash", str(ROOT / "tools/fetch-verified.sh"),
                 str(root / "source.tar"), digest, *urls],
                env=dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                         FETCH_LOG=str(root / "requests.json"), FETCH_MODE=mode),
                capture_output=True, text=True,
            )
            records = json.loads((root / "requests.json").read_text()) \
                if (root / "requests.json").exists() else []
            content = (root / "source.tar").read_bytes() if (root / "source.tar").exists() else None
            leftovers = list(root.glob("source.tar.part.*"))
            return result, records, content, leftovers

    def test_primary_success_uses_bounded_curl_and_pinned_hash(self):
        result, records, content, leftovers = self.invoke("ok")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(content, PAYLOAD)
        self.assertEqual(len(records), 1)
        for option, value in (("--connect-timeout", "10"), ("--max-time", "120"),
                              ("--retry", "1"), ("--retry-max-time", "45"),
                              ("--speed-time", "30")):
            self.assertEqual(records[0][records[0].index(option) + 1], value)
        self.assertIn("--fail", records[0])
        self.assertEqual(leftovers, [])

    def test_network_failure_uses_only_explicit_mirror_with_same_hash(self):
        result, records, content, leftovers = self.invoke("fallback")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(records), 2)
        self.assertIn("https://mirror.test/source", records[1])
        self.assertEqual(content, PAYLOAD)
        self.assertEqual(leftovers, [])

    def test_bad_checksum_never_publishes_or_falls_back(self):
        result, records, content, leftovers = self.invoke("corrupt")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(records), 1)
        self.assertIsNone(content)
        self.assertEqual(leftovers, [])

    def test_all_network_failures_are_finite_and_leave_no_archive(self):
        result, records, content, leftovers = self.invoke("offline")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(records), 2)
        self.assertIsNone(content)
        self.assertEqual(leftovers, [])

    def test_non_https_and_invalid_digest_fail_before_download(self):
        for urls, digest in ((("http://primary.test/source",), DIGEST),
                             (("https://primary.test/source",), "not-a-hash")):
            result, records, content, leftovers = self.invoke("ok", urls, digest)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(records, [])
            self.assertIsNone(content)
            self.assertEqual(leftovers, [])

    def test_makefile_uses_checked_downloader_and_explicit_ffmpeg_mirror(self):
        source = (ROOT / "Makefile").read_text()
        self.assertIn("bash tools/fetch-verified.sh", source)
        self.assertIn("https://distfiles.macports.org/ffmpeg/ffmpeg-", source)


if __name__ == "__main__":
    unittest.main()
