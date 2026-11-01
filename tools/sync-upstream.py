#!/usr/bin/env python3
"""Trusted Git/API maintenance only; never execute files from a merge candidate.

The workflow copies this file from trusted master to RUNNER_TEMP before Git
changes checkout. No dependencies beyond Python, Git and (in Actions) gh.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPOSITORY = "pablovesnine/MHGURecomp"
UPSTREAM = "https://github.com/morerokk/MHGURecomp.git"
BRANCH = "bot/upstream-sync"
LEGACY_BRANCH = "linux-arm64-0118"
MARKER = "[upstream-sync]"
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
CONTEXT = "upstream-sync/aarch64"
COMMENT = "<!-- mhgurecomp-upstream-sync -->"
ISSUE_TITLE = "[upstream-sync] Upstream merge needs attention"


class Intervention(RuntimeError):
    """Stop without modifying remote history; request human intervention."""


class SyncGit:
    def __init__(self, repo):
        self.repo = Path(repo)

    def run(self, *args, check=True):
        env = dict(os.environ, GIT_AUTHOR_NAME=BOT_NAME, GIT_AUTHOR_EMAIL=BOT_EMAIL,
                   GIT_COMMITTER_NAME=BOT_NAME, GIT_COMMITTER_EMAIL=BOT_EMAIL,
                   GIT_TERMINAL_PROMPT="0")
        result = subprocess.run(
            ["git", "-C", str(self.repo), "-c", "core.hooksPath=/dev/null",
             "-c", "commit.gpgsign=false", *args],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        if check and result.returncode:
            # Do not print stderr, which might contain credential-bearing URLs.
            raise Intervention(f"Git {args[0]} failed; remote history was not reset.")
        return result

    def git(self, *args):
        return self.run(*args).stdout.strip()

    def refresh(self):
        self.git("fetch", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")
        self.git("fetch", "upstream", "+refs/heads/master:refs/remotes/upstream/master")

    def ancestor(self, older, newer):
        result = self.run("merge-base", "--is-ancestor", older, newer, check=False)
        if result.returncode not in (0, 1):
            raise Intervention("Cannot establish commit ancestry.")
        return result.returncode == 0

    def remote_tip(self, branch):
        lines = self.git("ls-remote", "--heads", "origin", f"refs/heads/{branch}")
        return lines.split()[0] if lines else None

    def delete_merged(self, branch, expected):
        if branch not in (BRANCH, LEGACY_BRANCH):
            raise Intervention("Refusing cleanup outside the two allowed branch names.")
        self.git("fetch", "origin", "+refs/heads/master:refs/remotes/origin/master")
        if not self.ancestor(expected, "origin/master"):
            raise Intervention(f"Keep {branch}: its exact tip is not contained in master.")
        # The lease is also the deletion's compare-and-swap: a concurrent update,
        # even a fast-forward, must not be discarded.
        self.git("push", f"--force-with-lease=refs/heads/{branch}:{expected}",
                 "origin", f":refs/heads/{branch}")

    def owned(self, tip, base, upstream):
        extra = self.git("rev-list", tip, f"^{base}", f"^{upstream}").splitlines()
        subjects = {MARKER + " Merge fork master", MARKER + " Merge upstream master"}
        for sha in extra:
            fields = self.git("show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%s%n%P", sha).splitlines()
            if (len(fields) != 6 or fields[:4] != [BOT_NAME, BOT_EMAIL, BOT_NAME, BOT_EMAIL]
                    or fields[4] not in subjects or len(fields[5].split()) != 2):
                raise Intervention(
                    f"Keep {BRANCH}: unrecognized/human commit {sha}; resolve manually.")

    def merge(self, ref, message):
        if self.ancestor(ref, "HEAD"):
            return
        result = self.run("merge", "--no-ff", "--no-edit", "-m", MARKER + " " + message,
                          ref, check=False)
        if result.returncode:
            paths = self.git("diff", "--name-only", "--diff-filter=U")
            self.run("merge", "--abort", check=False)
            raise Intervention("Merge stopped without resolution. Conflicting paths:\n" +
                               (paths or "(Git could not prepare a merge.)"))

    def prepare(self):
        base = self.git("rev-parse", "origin/master")
        upstream = self.git("rev-parse", "upstream/master")
        exists = self.run("rev-parse", "--verify", f"refs/remotes/origin/{BRANCH}", check=False)
        previous = exists.stdout.strip() if exists.returncode == 0 else None
        if previous and self.ancestor(previous, base):
            self.delete_merged(BRANCH, previous)
            previous = None
            if self.ancestor(upstream, base):
                return {"outcome": "cleaned"}
        if previous:
            self.owned(previous, base, upstream)
        if self.ancestor(upstream, base):
            if previous:
                raise Intervention("Upstream is already in master, but the bot branch is not. "
                                   "Keep the branch and review it manually.")
            return {"outcome": "noop"}
        self.git("checkout", "--detach", previous or base)
        if previous:
            self.merge(base, "Merge fork master")
        self.merge(upstream, "Merge upstream master")
        sha = self.git("rev-parse", "HEAD")
        return {"outcome": "candidate", "sha": sha, "previous": previous,
                "changed": sha != previous}

    def push_candidate(self, sha, previous):
        if self.remote_tip(BRANCH) != previous:
            raise Intervention("Bot branch changed concurrently; it was not overwritten.")
        # A normal fast-forward push, never a force update or reset.
        self.git("push", "origin", f"{sha}:refs/heads/{BRANCH}")


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
        raise Intervention(f"GitHub API {method} {path.split('?')[0]} failed.")
    data = json.loads(result.stdout) if result.stdout.strip() else None
    return [item for page in data for item in page] if paginate else data


def pull_request():
    prs = api(f"pulls?state=open&base=master&head=pablovesnine:{BRANCH}&per_page=100")
    if len(prs) > 1:
        raise Intervention("Multiple bot PRs found; review them manually.")
    return prs[0] if prs else None


def comment(number, text):
    comments = api(f"issues/{number}/comments?per_page=100", paginate=True)
    owned = [c for c in comments if c["user"]["login"] == BOT_NAME
             and c["body"].startswith(COMMENT)]
    body = COMMENT + "\n" + text
    if owned:
        if owned[-1]["body"] != body:
            api(f'issues/comments/{owned[-1]["id"]}', "PATCH", {"body": body})
    else:
        api(f"issues/{number}/comments", "POST", {"body": body})


def notify_failure(message, run_url):
    text = f"Synchronization stopped; no conflict resolution or history reset was applied.\n\n" \
           f"```text\n{message}\n```\n\nRun: {run_url}\n\nHuman intervention is required."
    pr = pull_request()
    if pr:
        comment(pr["number"], text)
    elif api("")["has_issues"]:
        # Reuse the bot's single tracking issue even if a human has closed it.
        # A later failed run must not open another issue every six hours.
        issues = api("issues?state=all&per_page=100", paginate=True)
        owned = [i for i in issues if i["title"] == ISSUE_TITLE
                 and i["user"]["login"] == BOT_NAME and "pull_request" not in i]
        if owned:
            api(f'issues/{owned[0]["number"]}', "PATCH", {"body": COMMENT + "\n" + text})
        else:
            api("issues", "POST", {"title": ISSUE_TITLE, "body": COMMENT + "\n" + text})
    else:
        print("::error::Issues are disabled and there is no open sync PR. See this failed run.")


def write_outputs(**values):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        for key, value in values.items():
            out.write(f"{key}={value}\n")


def already_tested(sha):
    # GitHub returns newest first. Only this dedicated status context counts.
    statuses = api(f"commits/{sha}/statuses?per_page=100", paginate=True)
    latest = next((s for s in statuses if s["context"] == CONTEXT), None)
    return latest is not None and latest["state"] in ("success", "failure", "error")


def prepare(args, run_url):
    git = SyncGit(args.repo)
    # Fixed source and destination, irrespective of local remote configuration.
    git.git("remote", "set-url", "origin", f"https://github.com/{REPOSITORY}.git")
    if git.run("remote", "get-url", "upstream", check=False).returncode:
        git.git("remote", "add", "upstream", UPSTREAM)
    else:
        git.git("remote", "set-url", "upstream", UPSTREAM)
    git.refresh()
    if args.cleanup_legacy:
        tip = git.remote_tip(LEGACY_BRANCH)
        if tip:
            git.git("fetch", "origin", f"refs/heads/{LEGACY_BRANCH}")
            git.delete_merged(LEGACY_BRANCH, tip)
    result = git.prepare()
    write_outputs(should_validate="false")
    if result["outcome"] != "candidate":
        print(f"Synchronization: {result['outcome']}; no build required.")
        return
    if result["changed"]:
        git.push_candidate(result["sha"], result["previous"])
    if git.remote_tip(BRANCH) != result["sha"]:
        raise Intervention("The bot branch moved after preparation; preserve it and review manually.")
    should_validate = args.retry or not already_tested(result["sha"])
    if not should_validate:
        print(f"Candidate {result['sha']} already tested; no writes or build required.")
        return
    pr = pull_request()
    if pr is None:
        pr = api("pulls", "POST", {
            "title": "Merge upstream master (Linux ARM64 validation)",
            "head": BRANCH, "base": "master",
            "body": "Normal merges from morerokk/MHGURecomp:master, preserving ancestry. "
                    "Review conflicts/platform changes and merge manually; no auto-merge.\n\n"
                    f"Validation run: {run_url}",
        })
    write_outputs(candidate_sha=result["sha"], pr_number=pr["number"],
                  should_validate="true")
    comment(pr["number"], f"Candidate `{result['sha']}` is queued for read-only "
            f"AArch64 validation.\n\nRun: {run_url}\n\nMerge remains a human decision.")


def report(args, run_url):
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        raise Intervention("Reporter requires an exact 40-character commit SHA.")
    pr_number = int(args.pr)
    pr = api(f"pulls/{pr_number}")
    if (pr["head"]["ref"] != BRANCH or pr["head"]["repo"]["full_name"] != REPOSITORY
            or pr["base"]["ref"] != "master"):
        raise Intervention("Reporter refuses a PR outside the fixed sync branch/base/repository.")
    base_sha = pr["base"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
        raise Intervention("Reporter requires an exact current master revision.")
    comparison = api(f"compare/{base_sha}...{args.sha}")
    current_base_included = comparison["status"] in ("ahead", "identical")
    state = "success" if args.result == "success" else "failure"
    if not current_base_included:
        state = "failure"
    api(f"statuses/{args.sha}", "POST", {
        "state": state, "context": CONTEXT, "target_url": run_url,
        "description": (f"AArch64 candidate validation: {args.result}"
                        if current_base_included else
                        "master advanced; refresh the merge candidate"),
    })
    stale = "" if pr["head"]["sha"] == args.sha else (
        "\n\nThe PR has moved: this result does NOT validate its current tip.")
    if not current_base_included:
        stale += ("\n\nmaster advanced beyond this candidate. Refresh the normal "
                  "merge and rerun validation before merging.")
    comment(pr_number, f"Candidate `{args.sha}`: **{args.result}**.\n\nRun: {run_url}"
            f"{stale}\n\nReview and merge manually; this bot never auto-merges.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "report"))
    parser.add_argument("--repo", default=".")
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--cleanup-legacy", action="store_true")
    parser.add_argument("--sha", default="")
    parser.add_argument("--pr", default="")
    parser.add_argument("--result", choices=("success", "failure", "cancelled", "skipped"))
    args = parser.parse_args()
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_REF") != "refs/heads/master"):
        parser.error("Maintenance runs only on pablovesnine/MHGURecomp master.")
    run_url = (f"https://github.com/{REPOSITORY}/actions/runs/"
               f"{os.environ['GITHUB_RUN_ID']}")
    try:
        if args.mode == "prepare":
            prepare(args, run_url)
        else:
            report(args, run_url)
    except (Intervention, ValueError) as exc:
        print(f"::error::{exc}")
        if args.mode == "prepare":
            try:
                notify_failure(str(exc), run_url)
            except Intervention as notification:
                print(f"::error::{notification} See this failed run for the original error.")
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(f"## Upstream synchronization stopped\n\n{exc}\n\n{run_url}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
