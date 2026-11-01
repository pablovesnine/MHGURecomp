#!/usr/bin/env python3
"""Trusted Git/API automation. Never execute code from the candidate checkout.

Policy comes from the expected fork master, not upstream or the candidate.
Only an explicit protected/deleted path can override a normal Git merge.
"""
import argparse
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
BRANCH = "bot/upstream-sync"
LEGACY_BRANCH = "linux-arm64-0118"
MARKER = "[upstream-sync]"
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
CONTEXT = "upstream-sync/aarch64"
POLICY = "tools/fork-policy.json"
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

    def run(self, *args, check=True):
        env = dict(os.environ, GIT_AUTHOR_NAME=BOT_NAME, GIT_AUTHOR_EMAIL=BOT_EMAIL,
                   GIT_COMMITTER_NAME=BOT_NAME, GIT_COMMITTER_EMAIL=BOT_EMAIL,
                   GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1",
                   GIT_LITERAL_PATHSPECS="1")
        result = subprocess.run(
            ["git", "-C", str(self.repo), "-c", "core.hooksPath=/dev/null",
             "-c", "commit.gpgsign=false", "-c", "core.quotePath=false", *args],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
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
        self.git("fetch", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")
        self.git("fetch", "upstream", "+refs/heads/master:refs/remotes/upstream/master")

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
        return hashlib.sha256(self.policy_bytes(base).encode()).hexdigest()

    def policy(self, base):
        try:
            return validate_policy(json.loads(self.policy_bytes(base)))
        except (ValueError, TypeError) as exc:
            raise Intervention("Trusted fork policy is not valid JSON.") from exc

    def context(self):
        base = exact(self.git("rev-parse", "origin/master"))
        upstream = exact(self.git("rev-parse", "upstream/master"))
        previous = self.run("rev-parse", "--verify", f"refs/remotes/origin/{BRANCH}", check=False)
        result = {"base": base, "upstream": upstream, "policy": self.policy_digest(base),
                  "previous": previous.stdout.strip() if previous.returncode == 0 else None}
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

    def owned(self, tip, base, upstream):
        extra = self.git("rev-list", tip, f"^{base}", f"^{upstream}").splitlines()
        subjects = {MARKER + " Merge fork master", MARKER + " Merge upstream master"}
        for sha in extra:
            fields = self.git("show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%s%n%P", sha).splitlines()
            if (len(fields) != 6 or fields[:4] != [BOT_NAME, BOT_EMAIL, BOT_NAME, BOT_EMAIL]
                    or fields[4] not in subjects or len(fields[5].split()) != 2):
                raise Intervention(f"Keep {BRANCH}: unrecognized/human commit {sha}; resolve manually.")

    def enforce(self, base, refs, policy):
        base_paths = self.paths(base)
        paths = set(base_paths)
        for ref in refs:
            paths |= self.paths(ref)
        paths |= set(self.run("ls-files", "-z").stdout.rstrip("\0").split("\0")) - {""}
        omitted = []
        for path in sorted(paths):
            kind = classify(policy, path)
            if kind is None:
                raise Intervention("Unclassified path requires policy review: " + repr(path))
            if kind == "keep" and path in base_paths:
                self.git("restore", "--source=" + base, "--staged", "--worktree", "--", path)
            elif kind in ("keep", "remove"):
                self.git("rm", "-f", "--ignore-unmatch", "--", path)
            if kind != "shared":
                omitted.append(path)
        return omitted

    def merge(self, ref, base, policy, message):
        if self.ancestor(ref, "HEAD"):
            return []
        result = self.run("merge", "--no-ff", "--no-commit", "--no-edit", ref, check=False)
        conflicts = self.run("diff", "--name-only", "-z", "--diff-filter=U").stdout
        if result.returncode and not conflicts:
            raise GitFailure("Git could not prepare the merge (not a path conflict).")
        try:
            omitted = self.enforce(base, ("HEAD", ref), policy)
            remaining = self.git("diff", "--name-only", "--diff-filter=U")
            if remaining:
                raise Intervention("Shared merge conflicts require intervention:\n" + remaining)
            self.git("commit", "-m", MARKER + " " + message)
            return omitted
        except (Intervention, GitFailure):
            self.run("merge", "--abort", check=False)
            raise

    def prepare(self):
        context = self.context()
        base, upstream, previous = (context[k] for k in ("base", "upstream", "previous"))
        policy = self.policy(base)
        if previous and self.ancestor(previous, base):
            self.delete_merged(BRANCH, previous)
            previous = None
            if self.ancestor(upstream, base):
                return dict(context, outcome="cleaned")
        if previous:
            self.owned(previous, base, upstream)
        if self.ancestor(upstream, base):
            if previous:
                raise Intervention("Upstream is in master, but the bot branch is not; preserve and review it.")
            return dict(context, outcome="noop")
        self.git("checkout", "--detach", previous or base)
        omitted = []
        if previous:
            omitted += self.merge(base, base, policy, "Merge fork master")
        omitted += self.merge(upstream, base, policy, "Merge upstream master")
        sha = exact(self.git("rev-parse", "HEAD"))
        self.verify_policy(sha, base, policy)
        # Report only upstream changes actually excluded, not every protected file.
        changed = set(self.run("diff", "--name-only", "-z", base + "..." + upstream).stdout.split("\0"))
        omitted = sorted(set(omitted) & changed)
        return dict(context, outcome="candidate", sha=sha, previous=previous,
                    changed=sha != previous, omitted=omitted)

    def verify_policy(self, sha, base, policy):
        current, original = self.paths(sha), self.paths(base)
        for path in current | original:
            kind = classify(policy, path)
            if kind is None:
                raise Intervention("Unclassified candidate path: " + repr(path))
            if kind == "remove" and path in current:
                raise Intervention("Candidate resurrected a retired path: " + repr(path))
            if kind == "keep":
                a = self.git("ls-tree", sha, "--", path)
                b = self.git("ls-tree", base, "--", path)
                if a != b:
                    raise Intervention("Candidate changed protected path: " + repr(path))

    def push_candidate(self, sha, previous):
        if self.remote_tip(BRANCH) != previous:
            raise Intervention("Bot branch changed concurrently; it was not overwritten.")
        self.git("push", "origin", f"{exact(sha)}:refs/heads/{BRANCH}")

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
        if not self.ancestor(base, sha) or not self.ancestor(upstream, sha):
            raise Intervention("Candidate does not contain the expected source ancestors.")
        if len(self.git("show", "-s", "--format=%P", sha).split()) != 2:
            raise Intervention("Candidate must be a normal two-parent merge commit.")
        self.owned(sha, base, upstream)
        self.verify_policy(sha, base, self.policy(base))
        # A normal push's pre-push hook sees the server-advertised old OID.
        # Checking it closes the ls-remote -> push race even when the racing
        # revision is an ancestor of our candidate. Server CAS covers the rest.
        # There is NO force/lease option on the master push.
        with tempfile.TemporaryDirectory(prefix="trusted-sync-hooks-") as directory:
            hook = Path(directory) / "pre-push"
            hook.write_text(
                "#!/usr/bin/env python3\nimport sys\n"
                "rows = [line.split() for line in sys.stdin]\n"
                f"expected = [['HEAD', '{sha}', 'refs/heads/master', '{base}']]\n"
                f"ok = len(rows) == 1 and rows[0][1:] == expected[0][1:]\n"
                "sys.exit(0 if ok else 'master changed in push advertisement; refusing promotion')\n")
            hook.chmod(0o700)
            self.git("-c", f"core.hooksPath={directory}", "push", "origin",
                     f"{sha}:refs/heads/master")
        self.delete_merged(BRANCH, sha)


def api(path, method="GET", body=None, paginate=False):
    endpoint = f"repos/{REPOSITORY}" + (f"/{path}" if path else "")
    cmd = ["gh", "api", endpoint, "--method", method]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    if body is not None:
        cmd += ["--input", "-"]
    result = subprocess.run(cmd, input=json.dumps(body) if body is not None else None,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise GitFailure(f"GitHub API {method} {path.split('?')[0]} failed.")
    data = json.loads(result.stdout) if result.stdout.strip() else None
    return [item for page in data for item in page] if paginate else data


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
    git.fixed_remotes()
    git.refresh()
    context = git.context()
    output = dict(should_validate="false", outcome="noop", candidate_sha="",
                  base=context["base"], upstream=context["upstream"],
                  policy=context["policy"], key=context["key"], message="")
    prior = issue_state()
    if not args.retry and prior.get("key") == context["key"] and prior.get("state") == "blocked":
        output.update(outcome="blocked", message="Unchanged known blocker; requires intervention. Use retry_validation to retry.")
        write_outputs(**output)
        print("::warning::" + output["message"])
        return
    try:
        if args.cleanup_legacy:
            tip = git.remote_tip(LEGACY_BRANCH)
            if tip:
                git.git("fetch", "origin", f"refs/heads/{LEGACY_BRANCH}")
                git.delete_merged(LEGACY_BRANCH, tip)
        result = git.prepare()
        output["outcome"] = result["outcome"]
        if result["outcome"] == "candidate":
            if result["changed"]:
                git.push_candidate(result["sha"], result["previous"])
            if git.remote_tip(BRANCH) != result["sha"]:
                raise Intervention("Bot branch moved after preparation; keep and review it.")
            # The dedup key must include the newly published branch tip.
            context = git.context()
            output.update(key=context["key"], candidate_sha=result["sha"])
            output["should_validate"] = "true" if args.retry or not already_tested(result["sha"]) else "false"
            output["message"] = "Upstream changes omitted by explicit fork policy:\n" + (
                "\n".join("- `" + p + "`" for p in result["omitted"]) or "(none)")
        else:
            output["message"] = "Upstream is already incorporated; no build required."
    except Intervention as exc:
        output.update(outcome="blocked", message=str(exc))
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
