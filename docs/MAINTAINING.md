# Maintaining the Linux ARM64 fork

`master` is the only permanent product branch. Preserve the upstream history
and merge updates normally; do not periodically replace this fork with
upstream's tree or squash away the imported ancestry.

## One-time GitHub setup

1. In this fork's **Actions** tab, enable workflows if GitHub has disabled
   them for the fork.
2. In **Settings → Actions → General**, permit the pinned actions used by
   the workflows and enable **Allow GitHub Actions to create and approve
   pull requests**. The jobs request their own limited permissions; a
   globally read/write default is not needed.
3. Enable the scheduled upstream-sync workflow. Its manual trigger is also
   available in Actions. GitHub can disable public-repository schedules
   after 60 days without repository activity; re-enable the workflow if
   needed rather than adding artificial keepalive commits.
4. After the first successful tools-image publication, check the
   `mhgurecomp-builder` package under the owner's **Packages**. Associate it
   with this repository, grant this repository Actions access if needed,
   and change visibility to **Public**. New packages can initially be
   private even when the repository is public.
5. Enable **Issues** in repository settings if reports and automatic
   conflict-tracking issues are wanted. The fork previously had Issues
   disabled.
6. Enable automatic deletion of merged PR head branches for Dependabot and
   manual update branches. The maintenance workflow's own deletion guard
   remains restricted to its explicitly named branches.

These settings may require owner permissions beyond Contents/Pull requests.
The automation does not store a personal access token: it uses the
short-lived `GITHUB_TOKEN` supplied to each job.

GitHub documents the relevant behavior in
[workflow trigger rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow),
[workflow activation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)
and the [Container registry guide](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## Upstream synchronization

The scheduled workflow checks `morerokk/MHGURecomp:master` every six hours.
It proposes changes in `bot/upstream-sync`, opening or updating one PR in
**this fork**, never in upstream. The candidate preserves the upstream and
fork histories through ordinary merges.

No new upstream commits means no compilation. An already checked candidate
is not rebuilt on every scheduled poll. The workflow explicitly invokes
the public ARM64 validation for a new candidate, rather than relying on a
bot push to start another workflow. GitHub may put PR-event runs created by
`GITHUB_TOKEN` into an approval-required state; the explicit sync validation
is the path used by this automation.

The result belongs to an exact candidate SHA. If `master` or upstream moves,
reevaluate the merge candidate and its checks. A result for an earlier tip
does not establish that a changed merge is safe.

### Review an update

Read the diff and test result linked from the PR. Pay particular attention
to build-system changes, platform additions, target dependencies and file
deletions: upstream remains multiplatform, while this fork deliberately is
not. A clean textual merge can still reintroduce unsupported instructions.

A green public-code check does not establish game/device compatibility.
Perform a private build and device test when the update warrants it, then
merge the PR with **Create a merge commit**, not squash/rebase.
The cleanup job deletes only designated temporary branches whose current
tips are already ancestors of `master`.

### Resolve a conflict

The bot does not resolve conflicts with blanket `ours` or `theirs`, nor
overwrite manual commits on its branch. Inspect the existing PR or the
workflow failure/issue. If no candidate branch could be created, start a
manual update from `master`:

```bash
git switch master
git pull --ff-only
git remote add upstream https://github.com/morerokk/MHGURecomp.git
git fetch upstream master
git switch -c manual/upstream-update
git merge --no-ff upstream/master
```

If `upstream` already exists, verify its URL instead of adding it again.
Resolve files individually and run the public checks:

```bash
git add <resolved-files>
git commit
bash tools/build-linux-release.sh --check --version 0 --jobs 2
git push -u origin manual/upstream-update
```

Open a PR to this fork's `master`. Preserve ARM64-only packaging and the
privacy boundary. Do not restore the binary updater just because upstream
changed it. If manually editing an existing bot PR instead, the bot will
stop automatic updates rather than erase those edits; finish and merge
that PR manually.

## CI and tools-image publication

Public checks run on an x86_64 runner. The tools container cross-compiles
the ARM64 runtime and uses QEMU for small tests, without a game dump.
The pipeline checks shell/workflow syntax, Python regression tests,
compiler probes, ELF/import ceilings, settings/locales, fault handling and
settings-panel navigation. A panel failure is a failure, not an advisory
exception.

Only a validated `master` build may publish
`ghcr.io/pablovesnine/mhgurecomp-builder:<full-source-SHA>`. PR and sync
candidates never publish. The publisher receives the same tested tools
image as a short-lived transport artifact, then loads and pushes it without
running candidate scripts. Its registry permissions are separated from the
read-only build job.

Check the recorded digest and try an anonymous pull from a clean Docker
configuration before calling the package publicly available:

```bash
revision="$(git rev-parse HEAD)"
docker pull "ghcr.io/pablovesnine/mhgurecomp-builder:$revision"
```

Use a temporary `DOCKER_CONFIG` with no stored login for an anonymous-access
test; ordinary `docker pull` may otherwise use existing credentials.
The wrapper verifies that the selected image is x86_64 and matches the source
revision. For a local rebuild from that commit's tracked source:

```bash
bash tools/build-linux-release.sh --check --version 0 --jobs 2 \
  --rebuild-image
```

The Ubuntu base digest and source revision identify important inputs, but
APT repositories can change. Retained package manifests and image digests
aid debugging; they are not a promise of bit-for-bit reproducibility.

Dependabot proposes grouped monthly Actions/Docker updates. Review and test
them like source updates. Do not automatically raise GLIBC/GLIBCXX ceilings
to make a dependency update pass.

## Safety boundaries

- Write-permission jobs operate only on trusted maintenance code, Git refs
  and GitHub APIs; candidate build/test code runs without write tokens.
- No `pull_request_target` job executes candidate code.
- No workflow receives a dump, game library, generated game source or save.
- No game archive is published to Releases, Actions artifacts or GHCR.
- Cache transport contains public build dependencies/tools, not private
  local `.linux-release/` output.
- Branch deletion is restricted to named maintenance branches and checks
  current ancestry; a concurrent or human advance is not discarded.

Inherited platform implementations and the updater SHA256 implementation
remain where shared code needs them. Dedicated Android packaging and
Windows launchers are not maintained entry points. Technical documents
outside the README may discuss upstream platforms as historical context.
