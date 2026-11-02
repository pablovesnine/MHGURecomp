#!/usr/bin/env python3
"""Trusted Git/API automation. Never execute code from the candidate checkout.

Policy comes from the expected fork master, not upstream or the candidate.
Only an explicit protected/deleted path can override a normal Git merge.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

REPOSITORY = "pablovesnine/MHGURecomp"
UPSTREAM = "https://github.com/morerokk/MHGURecomp.git"
UPSTREAM_REPOSITORY = "morerokk/MHGURecomp"
BRANCH = "bot/upstream-sync"
LEGACY_BRANCH = "linux-arm64-0118"
MARKER = "[upstream-sync]"
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
CONTEXT = "upstream-sync/aarch64"
POLICY = "tools/fork-policy.json"
RELEASE_STATE = "tools/upstream-release.tsv"
STATE_KEYS = ("schema", "algorithm", "repository", "release_id", "version", "tag",
              "tag_oid", "commit", "published_at", "fork_base", "migration_merge",
              "migration_source")
RELEASE_KEYS = ("release_id", "version", "tag", "tag_oid", "commit", "published_at")
ISSUE = 2
STATE_MARKER = "<!-- mhgu-sync-state "


class Intervention(RuntimeError):
    """An expected safety stop requiring human intervention."""


class GitFailure(RuntimeError):
    """A Git/transport failure, NOT an expected merge conflict."""


def exact(value, size=40):
    if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{size}}}", value):
        raise Intervention(f"An exact {size}-character hexadecimal revision is required.")
    return value


def numeric_version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", value):
        raise Intervention("Stable release tag/version must be numeric.")
    parts = [int(part) for part in value.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def publication(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        raise Intervention("Release publication must be a UTC ISO timestamp.")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise Intervention("Invalid release publication date.") from exc
    return value


def release_state_bytes(state):
    if (not isinstance(state, dict) or set(state) != set(STATE_KEYS)
            or any(not isinstance(v, str) for v in state.values())
            or state["schema"] != "1" or state["algorithm"] != "release-base-v1"
            or state["repository"] != UPSTREAM_REPOSITORY):
        raise Intervention("Invalid release state schema/algorithm/repository.")
    if not re.fullmatch(r"[1-9][0-9]*", state["release_id"]):
        raise Intervention("Release state requires a positive numeric release_id.")
    numeric_version(state["version"])
    if state["version"] != state["tag"]:
        raise Intervention("Release state version and numeric tag differ.")
    publication(state["published_at"])
    for key in ("tag_oid", "commit", "fork_base", "migration_merge", "migration_source"):
        exact(state[key])
    return "".join(key + "\t" + state[key] + "\n" for key in STATE_KEYS).encode("ascii")


def parse_release_state(raw):
    try:
        text = raw.decode("ascii")
        lines = text.splitlines(keepends=True)
        if (len(lines) != len(STATE_KEYS) or any(
                not line.endswith("\n") or "\r" in line or line.count("\t") != 1
                for line in lines)):
            raise ValueError
        pairs = [line[:-1].split("\t") for line in lines]
        if [key for key, _ in pairs] != list(STATE_KEYS):
            raise ValueError
        state = dict(pairs)
        if release_state_bytes(state) != raw:
            raise ValueError
        return state
    except (ValueError, UnicodeError, AttributeError) as exc:
        raise Intervention("Invalid/noncanonical release state TSV.") from exc


def stable_releases():
    data = api("releases?per_page=100", paginate=True, repository=UPSTREAM_REPOSITORY)
    if not isinstance(data, list):
        raise GitFailure("Upstream releases API did not return a list.")
    stable, identifiers = [], set()
    for record in data:
        if (not isinstance(record, dict) or type(record.get("id")) is not int
                or record["id"] <= 0 or record["id"] in identifiers
                or type(record.get("draft")) is not bool
                or type(record.get("prerelease")) is not bool):
            raise Intervention("Invalid/duplicate upstream release metadata.")
        identifiers.add(record["id"])
        if (not record["draft"] and not record["prerelease"]
                and record.get("published_at") is not None):
            publication(record.get("published_at"))
            stable.append(record)
    return stable


def validate_policy(data):
    if (not isinstance(data, dict) or set(data) != {"version", "keep", "remove", "shared"}
            or type(data["version"]) is not int or data["version"] != 1):
        raise Intervention("Invalid fork policy schema/version.")
    files = set()
    for kind in ("keep", "remove", "shared"):
        rules = data[kind]
        if not isinstance(rules, dict) or set(rules) != {"files", "prefixes"}:
            raise Intervention("Policy rules require files and prefixes.")
        for key in ("files", "prefixes"):
            values = rules[key]
            if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
                raise Intervention("Policy paths must be string lists.")
            if len(set(values)) != len(values):
                raise Intervention("Duplicate policy rule.")
            for value in values:
                path = value[:-1] if key == "prefixes" and value.endswith("/") else value
                if (not path or (key == "prefixes" and not value.endswith("/"))
                        or (key == "files" and value.endswith("/"))
                        or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", path)
                        or any(p in (".", "..", ".git") for p in path.split("/"))):
                    raise Intervention("Unsafe policy path: " + repr(value))
                if key == "files":
                    if value in files:
                        raise Intervention("Conflicting exact policy rules.")
                    files.add(value)
    return data


def classify(policy, path):
    # Exact shared exceptions permit sha256.c inside the retired updater tree.
    if path in policy["keep"]["files"] or any(
            path.startswith(p) for p in policy["keep"]["prefixes"]):
        return "keep"
    if path in policy["shared"]["files"]:
        return "shared"
    if path in policy["remove"]["files"] or any(
            path.startswith(p) for p in policy["remove"]["prefixes"]):
        return "remove"
    if any(path.startswith(p) for p in policy["shared"]["prefixes"]):
        return "shared"
    return None


class SyncGit:
    def __init__(self, repo):
        self.repo = Path(repo)

    def run(self, *args, check=True, binary=False, input=None, env_extra=None):
        env = dict(os.environ, GIT_AUTHOR_NAME=BOT_NAME, GIT_AUTHOR_EMAIL=BOT_EMAIL,
                   GIT_COMMITTER_NAME=BOT_NAME, GIT_COMMITTER_EMAIL=BOT_EMAIL,
                   GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1",
                   GIT_LITERAL_PATHSPECS="1")
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            ["git", "-C", str(self.repo), "-c", "core.hooksPath=/dev/null",
             "-c", "commit.gpgsign=false", "-c", "core.quotePath=false", *args],
            text=not binary, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        if check and result.returncode:
            # Remote stderr may include credentials: don't print it.
            raise GitFailure(f"Git {args[0]} failed (exit {result.returncode}); no reset attempted.")
        return result

    def git(self, *args):
        return self.run(*args).stdout.strip()

    def fixed_remotes(self):
        self.git("remote", "set-url", "origin", f"https://github.com/{REPOSITORY}.git")
        if self.run("remote", "get-url", "upstream", check=False).returncode:
            self.git("remote", "add", "upstream", UPSTREAM)
        else:
            self.git("remote", "set-url", "upstream", UPSTREAM)

    def refresh(self):
        self.git("fetch", "--prune", "--no-tags", "origin",
                 "+refs/heads/*:refs/remotes/origin/*")
        if self.git("rev-parse", "--is-shallow-repository") != "false":
            raise Intervention("Shallow history is unsafe for stable release synchronization.")
        grafts = Path(self.git("rev-parse", "--git-path", "info/grafts"))
        if not grafts.is_absolute():
            grafts = self.repo / grafts
        if grafts.exists() and grafts.stat().st_size:
            raise Intervention("Grafted history is unsafe for stable release synchronization.")

    def ancestor(self, older, newer):
        result = self.run("merge-base", "--is-ancestor", older, newer, check=False)
        if result.returncode not in (0, 1):
            raise GitFailure("Cannot establish commit ancestry.")
        return result.returncode == 0

    def remote_tip(self, branch):
        lines = self.git("ls-remote", "--heads", "origin", f"refs/heads/{branch}")
        return exact(lines.split()[0]) if lines else None

    def paths(self, ref):
        return set(self.run("ls-tree", "-rz", "--name-only", ref).stdout.rstrip("\0").split("\0")) - {""}

    def policy_bytes(self, base):
        result = self.run("show", f"{exact(base)}:{POLICY}", check=False)
        if result.returncode:
            raise Intervention("Trusted master has no fork policy; bootstrap it manually.")
        return result.stdout

    def policy_digest(self, base):
        return hashlib.sha256(self.run("show", f"{exact(base)}:{POLICY}", binary=True).stdout).hexdigest()

    def policy(self, base):
        try:
            return validate_policy(json.loads(self.policy_bytes(base)))
        except (ValueError, TypeError) as exc:
            raise Intervention("Trusted fork policy is not valid JSON.") from exc

    def state(self, base):
        entry = self.git("ls-tree", exact(base), "--", RELEASE_STATE)
        if not entry.startswith("100644 blob "):
            raise Intervention("Trusted master requires a regular protected release state TSV.")
        result = self.run("show", f"{base}:{RELEASE_STATE}", binary=True, check=False)
        if result.returncode:
            raise Intervention("Trusted master has no release state.")
        return parse_release_state(result.stdout)

    def resolve_tag(self, tag):
        numeric_version(tag)
        remote_ref = "refs/tags/" + tag

        def advertised():
            rows = self.git("ls-remote", "--refs", "upstream", remote_ref).splitlines()
            if len(rows) != 1 or rows[0].split()[1:] != [remote_ref]:
                raise Intervention("Upstream release tag is missing or ambiguous: " + tag)
            return exact(rows[0].split()[0])

        oid = advertised()
        ref = "refs/upstream-sync/tags/" + tag
        old = self.run("rev-parse", "--verify", ref, check=False)
        if old.returncode == 0 and old.stdout.strip() != oid:
            raise Intervention("Upstream tag moved after observation: " + tag)
        self.git("fetch", "--atomic", "--no-tags", "--no-write-fetch-head",
                 "--no-recurse-submodules", "upstream", oid + ":" + ref)
        peeled = self.run("rev-parse", "--verify", ref + "^{commit}", check=False)
        if peeled.returncode:
            raise Intervention("Release tag does not resolve to a commit: " + tag)
        if advertised() != oid:
            raise Intervention("Upstream tag moved during lookup: " + tag)
        return oid, exact(peeled.stdout.strip())

    def context(self):
        base = exact(self.git("rev-parse", "origin/master"))
        state = self.state(base)
        releases = stable_releases()
        tracked = next((r for r in releases if str(r["id"]) == state["release_id"]), None)
        if (tracked is None or tracked.get("tag_name") != state["tag"]
                or tracked["published_at"] != state["published_at"]):
            raise Intervention("Tracked release was withdrawn/reclassified or its identity changed.")
        tracked_oid, tracked_commit = self.resolve_tag(state["tag"])
        if (tracked_oid, tracked_commit) != (state["tag_oid"], state["commit"]):
            raise Intervention("Tracked release tag moved; refusing synchronization.")
        if not self.ancestor(state["commit"], base):
            raise Intervention("Recorded release is not an ancestor of fork master history.")
        selected = max(releases, key=lambda r: (r["published_at"], r["id"]))
        tag = selected.get("tag_name")
        numeric_version(tag)
        oid, upstream = ((tracked_oid, tracked_commit) if tag == state["tag"]
                         else self.resolve_tag(tag))
        release = dict(release_id=str(selected["id"]), version=tag, tag=tag,
                       tag_oid=oid, commit=upstream, published_at=selected["published_at"])
        if release != {key: state[key] for key in RELEASE_KEYS}:
            if numeric_version(tag) <= numeric_version(state["version"]):
                raise Intervention("Stable release downgrade/incompatible numeric version; review manually.")
            if not self.ancestor(state["commit"], upstream):
                raise Intervention("Stable release history diverges from tracked release ancestry.")
        previous = self.run("rev-parse", "--verify", f"refs/remotes/origin/{BRANCH}", check=False)
        result = {"base": base, "upstream": upstream, "policy": self.policy_digest(base),
                  "previous": exact(previous.stdout.strip()) if previous.returncode == 0 else None,
                  "release": release, "state": state}
        result["key"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        return result

    def delete_merged(self, branch, expected):
        if branch not in (BRANCH, LEGACY_BRANCH):
            raise Intervention("Refusing cleanup outside allowed temporary branch names.")
        exact(expected)
        self.git("fetch", "origin", "+refs/heads/master:refs/remotes/origin/master")
        if not self.ancestor(expected, "origin/master"):
            raise Intervention(f"Keep {branch}: its exact tip is not contained in master.")
        if self.remote_tip(branch) != expected:
            raise Intervention(f"Keep {branch}: its tip changed concurrently.")
        self.git("push", f"--force-with-lease=refs/heads/{branch}:{expected}",
                 "origin", f":refs/heads/{branch}")

    @staticmethod
    def subject(context):
        return MARKER + " Stable release " + context["release"]["version"]

    def candidate_identity(self, tip):
        fields = self.git("show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%s%n%P", exact(tip)).splitlines()
        if (len(fields) != 6 or fields[:4] != [BOT_NAME, BOT_EMAIL, BOT_NAME, BOT_EMAIL]
                or not re.fullmatch(re.escape(MARKER) + r" Stable release [0-9]+(?:\.[0-9]+)*",
                                    fields[4]) or len(fields[5].split()) != 2):
            raise Intervention(f"Keep {BRANCH}: unrecognized/human candidate; resolve manually.")
        return fields

    def owned(self, tip, context):
        fields = self.candidate_identity(tip)
        if (fields[4] != self.subject(context)
                or fields[5].split() != [context["base"], context["upstream"]]):
            raise Intervention(f"Keep {BRANCH}: stale candidate context; resolve manually.")

    def generated_state(self, context):
        state = dict(context["state"], **context["release"], fork_base=context["base"])
        return release_state_bytes(state)

    def merge_tree(self, context, policy):
        """Compute the only promotable tree without touching HEAD, index or worktree."""
        base, upstream, tracked = context["base"], context["upstream"], context["state"]["commit"]
        if classify(policy, RELEASE_STATE) != "keep":
            raise Intervention("Release state must be explicitly protected by trusted fork policy.")
        # --merge-base is mandatory: ordinary ancestry would skip reverted changes.
        result = self.run("merge-tree", "--write-tree", "--name-only", "-z",
                          "--merge-base=" + tracked, base, upstream, check=False)
        if result.returncode not in (0, 1):
            raise GitFailure("Git merge-tree with explicit --merge-base failed; Git 2.43+ is required.")
        fields = result.stdout.split("\0")
        tree = exact(fields[0])
        conflicts = []
        for path in fields[1:]:
            if not path:
                break
            conflicts.append(path)
        if result.returncode == 1 and not conflicts:
            raise GitFailure("Git merge-tree failed without resolvable path conflicts.")
        for path in conflicts:
            kind = classify(policy, path)
            if kind not in ("keep", "remove"):
                raise Intervention("Shared/unknown merge conflict requires intervention: " + repr(path))
        original = self.paths(base)
        paths = original | self.paths(tracked) | self.paths(upstream) | self.paths(tree)
        omitted = []
        with tempfile.TemporaryDirectory(prefix="trusted-sync-index-") as directory:
            env = {"GIT_INDEX_FILE": str(Path(directory) / "index")}
            self.run("read-tree", tree, env_extra=env)
            # Delete first so file/directory replacements never restore an upstream child.
            for path in sorted(paths):
                kind = classify(policy, path)
                if kind is None:
                    raise Intervention("Unclassified path requires policy review: " + repr(path))
                if kind != "shared":
                    self.run("update-index", "--force-remove", "--", path, env_extra=env)
                    omitted.append(path)
            for path in sorted(original):
                if classify(policy, path) == "keep" and path != RELEASE_STATE:
                    entry = self.git("ls-tree", base, "--", path).split("\t", 1)[0].split()
                    self.run("update-index", "--add", "--cacheinfo", entry[0], entry[2],
                             path, env_extra=env)
            state_oid = exact(self.run("hash-object", "-w", "--stdin", binary=True,
                                      input=self.generated_state(context)).stdout.decode().strip())
            self.run("update-index", "--add", "--cacheinfo", "100644", state_oid,
                     RELEASE_STATE, env_extra=env)
            tree = exact(self.run("write-tree", env_extra=env).stdout.strip())
        self.verify_policy(tree, base, policy, context)
        changed = set(self.run("diff", "--name-only", "-z", tracked, upstream).stdout.split("\0"))
        return tree, sorted(set(omitted) & changed)

    def prepare(self):
        context = self.context()
        base, upstream, previous = (context[k] for k in ("base", "upstream", "previous"))
        policy = self.policy(base)
        if classify(policy, RELEASE_STATE) != "keep":
            raise Intervention("Release state must be protected by trusted fork policy.")
        same_release = context["release"] == {key: context["state"][key] for key in RELEASE_KEYS}
        cleaned = False
        if previous and self.ancestor(previous, base):
            self.candidate_identity(previous)
            self.delete_merged(BRANCH, previous)
            previous = None
            cleaned = True
            context["previous"] = None
        if previous:
            self.owned(previous, context)
        if same_release:
            if previous:
                raise Intervention("Tracked release unchanged but bot candidate is stale; preserve and review it.")
            return dict(context, outcome="cleaned" if cleaned else "noop")
        tree, omitted = self.merge_tree(context, policy)
        if previous:
            if self.git("rev-parse", previous + "^{tree}") != tree:
                raise Intervention(f"Keep {BRANCH}: candidate tree/context was tampered with.")
            sha = previous
        else:
            sha = exact(self.git("commit-tree", tree, "-p", base, "-p", upstream,
                                 "-m", self.subject(context)))
        return dict(context, outcome="candidate", sha=sha, previous=previous,
                    changed=sha != previous, omitted=omitted)

    def verify_policy(self, sha, base, policy, context):
        current, original = self.paths(sha), self.paths(base)
        for path in current | original:
            kind = classify(policy, path)
            if kind is None:
                raise Intervention("Unclassified candidate path: " + repr(path))
            if kind == "remove" and path in current:
                raise Intervention("Candidate resurrected a retired path: " + repr(path))
            if kind == "keep":
                if path == RELEASE_STATE:
                    result = self.run("show", f"{sha}:{path}", binary=True, check=False)
                    entry = self.git("ls-tree", sha, "--", path)
                    if (result.returncode or not entry.startswith("100644 blob ")
                            or result.stdout != self.generated_state(context)):
                        raise Intervention("Candidate release state differs from exact generated bytes/mode.")
                    continue
                a = self.git("ls-tree", sha, "--", path)
                b = self.git("ls-tree", base, "--", path)
                if a != b:
                    raise Intervention("Candidate changed protected path: " + repr(path))

    def push_candidate(self, sha, previous):
        if self.remote_tip(BRANCH) != previous:
            raise Intervention("Bot branch changed concurrently; it was not overwritten.")
        context = self.context()
        if context["previous"] != previous:
            raise Intervention("Candidate branch context changed; refusing publication.")
        self.owned(sha, context)
        tree, _ = self.merge_tree(context, self.policy(context["base"]))
        if self.git("rev-parse", exact(sha) + "^{tree}") != tree:
            raise Intervention("Candidate tree differs from the current stable release context.")
        if self.context() != context:
            raise Intervention("Release context changed before candidate publication.")
        self.push_cas(BRANCH, exact(sha), exact(previous) if previous else "0" * 40)

    def push_cas(self, branch, sha, expected):
        # Normal push, with advertised-old-OID CAS even if the racing tip is
        # an ancestor of our candidate. Server CAS closes the remaining race.
        if branch not in ("master", BRANCH):
            raise Intervention("Refusing push outside the allowed synchronization branches.")
        exact(sha)
        exact(expected)
        with tempfile.TemporaryDirectory(prefix="trusted-sync-hooks-") as directory:
            hook = Path(directory) / "pre-push"
            hook.write_text(
                "#!/usr/bin/env python3\nimport sys\n"
                "rows = [line.split() for line in sys.stdin]\n"
                f"expected = ['{sha}', 'refs/heads/{branch}', '{expected}']\n"
                "ok = len(rows) == 1 and rows[0][1:] == expected\n"
                "sys.exit(0 if ok else 'branch changed in push advertisement; refusing synchronization')\n")
            hook.chmod(0o700)
            self.git("-c", f"core.hooksPath={directory}", "push", "origin",
                     f"{sha}:refs/heads/{branch}")

    def promote(self, sha, base, upstream, policy_hash):
        for value in (sha, base, upstream):
            exact(value)
        exact(policy_hash, 64)
        self.refresh()
        if self.remote_tip("master") != base:
            raise Intervention("master advanced; refusing promotion. No destructive retry.")
        if self.remote_tip(BRANCH) != sha:
            raise Intervention("Candidate branch changed; refusing promotion.")
        if self.policy_digest(base) != policy_hash:
            raise Intervention("Trusted policy changed; refusing promotion.")
        context = self.context()
        if context["base"] != base or context["upstream"] != upstream:
            raise Intervention("Stable release/base changed; refusing promotion.")
        if context["release"] == {key: context["state"][key] for key in RELEASE_KEYS}:
            raise Intervention("No new stable release to promote.")
        self.owned(sha, context)
        tree, _ = self.merge_tree(context, self.policy(base))
        if self.git("rev-parse", sha + "^{tree}") != tree:
            raise Intervention("Candidate tree differs from recomputed trusted stable release tree.")
        if self.context() != context:
            raise Intervention("Release context changed before master promotion.")
        # There is NO force/lease option on the master push.
        self.push_cas("master", sha, base)
        self.delete_merged(BRANCH, sha)


def api(path, method="GET", body=None, paginate=False, repository=REPOSITORY):
    if repository not in (REPOSITORY, UPSTREAM_REPOSITORY):
        raise Intervention("API repository is not explicitly allowed.")
    if repository == UPSTREAM_REPOSITORY and (method != "GET" or path != "releases?per_page=100"):
        raise Intervention("Upstream API access is restricted to the published release list.")
    endpoint = f"repos/{repository}" + (f"/{path}" if path else "")
    cmd = ["gh", "api", endpoint, "--method", method]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    if body is not None:
        cmd += ["--input", "-"]
    result = subprocess.run(cmd, input=json.dumps(body) if body is not None else None,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise GitFailure(f"GitHub API {method} {path.split('?')[0]} failed.")
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else None
        if paginate:
            if not isinstance(data, list) or any(not isinstance(page, list) for page in data):
                raise ValueError
            return [item for page in data for item in page]
        return data
    except ValueError as exc:
        raise GitFailure("GitHub API returned malformed JSON/pagination.") from exc


def state_marker(state):
    return STATE_MARKER + json.dumps(state, sort_keys=True) + " -->"


def parse_state(body):
    for line in (body or "").splitlines():
        if line.startswith(STATE_MARKER) and line.endswith(" -->"):
            try:
                result = json.loads(line[len(STATE_MARKER):-4])
                return result if isinstance(result, dict) else {}
            except ValueError:
                pass
    return {}


def issue_state():
    return parse_state(api(f"issues/{ISSUE}")["body"])


def update_issue(state, message, run_url):
    # Reuse issue #2, including reopening it. Never open routine PRs/issues.
    issue = api(f"issues/{ISSUE}")
    old = parse_state(issue["body"])
    desired = "closed" if state["state"] == "clean" else "open"
    # A no-op proves ancestry, not that a failed image was recovered.
    # Keep the recovery instructions until an operator verifies publication
    # and closes the issue, or another update publishes successfully.
    if (desired == "closed" and old.get("state") == "publication-failed"
            and issue["state"] == "open" and not state.get("sha")):
        return
    if (old.get("key") == state.get("key") and old.get("state") == state["state"]
            and issue["state"] == desired):
        return
    if desired == "closed" and issue["state"] == "closed":
        return
    body = (state_marker(state) + "\n## Automatic upstream synchronization\n\n"
            + message + "\n\nRun: " + run_url)
    api(f"issues/{ISSUE}", "PATCH", {"body": body, "state": desired})


def write_outputs(**values):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        for key, value in values.items():
            delimiter = "sync_" + uuid.uuid4().hex
            out.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def summary(text):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
        out.write(text + "\n")


def latest_status(sha):
    return next((s for s in api(f"commits/{exact(sha)}/statuses?per_page=100", paginate=True)
                 if s["context"] == CONTEXT), None)


def already_tested(sha):
    latest = latest_status(sha)
    return latest is not None and latest["state"] in ("success", "failure", "error")


def prepare(args, run_url):
    git = SyncGit(args.repo)
    output = dict(should_validate="false", outcome="noop", candidate_sha="",
                  base="", upstream="", policy="", key="", message="")
    try:
        git.fixed_remotes()
        git.refresh()
        context = git.context()
        output.update({key: context[key] for key in ("base", "upstream", "policy", "key")})
        prior = issue_state()
        if not args.retry and prior.get("key") == context["key"] and prior.get("state") == "blocked":
            output.update(outcome="blocked", message="Unchanged known blocker; requires intervention. Use retry_validation to retry.")
            write_outputs(**output)
            print("::warning::" + output["message"])
            return
        if args.cleanup_legacy:
            tip = git.remote_tip(LEGACY_BRANCH)
            if tip:
                git.git("fetch", "origin", f"refs/heads/{LEGACY_BRANCH}")
                git.delete_merged(LEGACY_BRANCH, tip)
        result = git.prepare()
        output.update({key: result[key] for key in ("base", "upstream", "policy", "key")})
        output["outcome"] = result["outcome"]
        if result["outcome"] == "candidate":
            if result["changed"]:
                git.push_candidate(result["sha"], result["previous"])
            if git.remote_tip(BRANCH) != result["sha"]:
                raise Intervention("Bot branch moved after preparation; keep and review it.")
            # The dedup key must include the newly published branch tip.
            context = git.context()
            if any(context.get(key) != result.get(key)
                   for key in ("base", "upstream", "policy", "release", "state")):
                raise Intervention("Stable release context changed during preparation; preserve candidate.")
            if context["previous"] != result["sha"]:
                raise Intervention("Candidate branch changed during preparation; preserve candidate.")
            output.update(key=context["key"], candidate_sha=result["sha"])
            output["should_validate"] = "true" if args.retry or not already_tested(result["sha"]) else "false"
            output["message"] = "Upstream changes omitted by explicit fork policy:\n" + (
                "\n".join("- `" + p + "`" for p in result["omitted"]) or "(none)")
        else:
            output["message"] = "Tracked stable release is unchanged; no build required."
    except (Intervention, GitFailure) as exc:
        output.update(outcome="blocked", message=str(exc))
        if not output["key"]:
            # No source fallback: these are only trusted-input blocker identifiers.
            try:
                output["base"] = exact(git.git("rev-parse", "origin/master"))
                output["policy"] = git.policy_digest(output["base"])
            except (Intervention, GitFailure):
                pass
            output["key"] = hashlib.sha256(json.dumps(
                {key: output[key] for key in ("base", "policy", "message")}, sort_keys=True).encode()).hexdigest()
        print("::warning::Synchronization requires intervention; see run summary.")
    write_outputs(**output)
    summary(f"## Upstream sync: {output['outcome']}\n\n"
            f"Base: `{output['base']}`\n\nUpstream: `{output['upstream']}`\n\n"
            f"Policy SHA256: `{output['policy']}`\n\n{output['message']}")


def promote(args, run_url):
    for value in (args.sha, args.base, args.upstream):
        exact(value)
    exact(args.policy, 64)
    latest = latest_status(args.sha)
    if (args.result != "success" or latest is None or latest["state"] != "success"
            or latest.get("target_url") != run_url):
        raise Intervention("Promotion requires green validation of this exact SHA in this run.")
    git = SyncGit(args.repo)
    git.fixed_remotes()
    git.promote(args.sha, args.base, args.upstream, args.policy)
    summary(f"Promoted tested two-parent merge `{args.sha}` by normal fast-forward push. "
            "Publication follows explicitly; a publication failure does not roll back master.")


def report(args, run_url):
    if args.sha:
        exact(args.sha)
    state = {"key": args.key, "state": "blocked"}
    if args.sha:
        state["sha"] = args.sha
    if args.phase == "validation":
        status = "success" if args.result == "success" else "failure"
        api(f"statuses/{exact(args.sha)}", "POST", {
            "state": status, "context": CONTEXT, "target_url": run_url,
            "description": f"AArch64 candidate validation: {args.result}",
        })
        if status == "success":
            return
        message = f"Candidate `{args.sha}` validation **{args.result}**. Tests/infra failed; not a policy conflict."
    elif args.outcome in ("noop", "cleaned") or args.promotion == "success":
        state["state"] = "clean"
        publication_failed = args.promotion == "success" and args.publication != "success"
        message = ("Upstream is incorporated in master. " +
                   ("Tools publication did not succeed; retry linux-publisher with this run's artifact/image ID "
                    "or rerun master CI. No rollback was attempted." if publication_failed
                    else "Synchronization complete."))
        if publication_failed:
            state["state"] = "publication-failed"
    elif args.outcome == "blocked":
        message = args.message + "\n\n**Requires intervention; no validation/promotion claimed.**"
    elif args.promotion == "failure":
        message = "Promotion failed or master/branch raced; preserve the candidate and inspect this run. No force/reset/retry was attempted."
    else:
        # Tested unchanged candidates and successful validation awaiting promotion
        # do not overwrite a more informative previous blocker.
        return
    update_issue(state, message, run_url)
    summary("## Synchronization report\n\n" + message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "promote", "report"))
    parser.add_argument("--repo", default=".")
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--cleanup-legacy", action="store_true")
    for name in ("sha", "base", "upstream", "policy", "key", "message", "outcome",
                 "promotion", "publication"):
        parser.add_argument("--" + name, default="")
    parser.add_argument("--phase", choices=("validation", "final"), default="final")
    parser.add_argument("--result", choices=("success", "failure", "cancelled", "skipped"), default="skipped")
    args = parser.parse_args()
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_REF") != "refs/heads/master"):
        parser.error("Maintenance runs only on pablovesnine/MHGURecomp master.")
    run_url = f"https://github.com/{REPOSITORY}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    try:
        {"prepare": prepare, "promote": promote, "report": report}[args.mode](args, run_url)
    except (Intervention, GitFailure, ValueError) as exc:
        print("::error::" + str(exc))
        summary(f"## Synchronization failed\n\n{exc}\n\n{run_url}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
