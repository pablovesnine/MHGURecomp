# Build both Linux packages

You can build both Linux packages on an x86-64 Linux PC using the same Docker
image. The compiler runs on your PC for both targets, cross-compiling when you
select ARM64; QEMU is only used to run small ARM64 checks. Both packages target
Linux with glibc, so these instructions do not apply to Android.

## Requirements

- An x86-64 Linux host.
- Git, Bash, `tar`, `flock`, `realpath`, and `sha256sum`.
- A local Docker engine.
- Your own complete MHGU 1.4.0 dump.
- Internet access for the first build.

Follow Docker's [installation guide](https://docs.docker.com/engine/install/),
then configure access without `sudo` using either the
[Linux post-installation steps](https://docs.docker.com/engine/install/linux-postinstall/)
or [rootless mode](https://docs.docker.com/engine/security/rootless/). Be aware
that membership in the `docker` group grants root-level privileges. Once Docker
is set up, run the build as your normal user rather than adding `sudo`.

As a starting point, allow 20 GB of free space in addition to your dump and
8 GB of RAM, and use two build jobs. These are planning margins, not measured
minimum requirements; a clean build time has not been established.

The image provides Ubuntu 24.04, Clang 18, GCC 13 target runtimes, and an ARM64
sysroot extracted from signed Ubuntu packages without running their ARM64
installers. The Makefile builds its pinned SDL3, shaderc, and FFmpeg sources
against that environment, keeping the existing glibc 2.39 and GLIBCXX_3.4.32
release ceilings.

## Use the published tools image

If a public image is available, downloading it is the easiest way to get
started. GitHub Actions checks the public code and publishes a tools image
to GHCR, not a playable game package or an Actions artifact containing one.
You then use that image to compile your own game library locally. A public
image can be downloaded anonymously, so you do not need a fork, a GitHub token,
or an Actions run of your own.

1. Check access to the local Docker server without `sudo`:

   ```bash
   docker info
   ```

2. Open the repository's **Actions** tab.
3. Select **Linux builder**.
4. Choose a successful run on `master` or `linux-arm64-0118` in a repository
   and branch you trust. Do not choose a PR run, since those do not publish images.
5. Check that both architecture jobs and **Publish the tools image** passed.
6. Copy the full source commit SHA from that run.
7. Clone the same repository and select that commit:

   ```bash
   REPOSITORY=morerokk/MHGURecomp
   OWNER=${REPOSITORY%%/*}
   read -r -p "Full source SHA from the successful run: " REVISION
   git clone "https://github.com/$REPOSITORY.git" MHGURecomp-linux
   cd MHGURecomp-linux
   git checkout --detach "$REVISION"
   IMAGE="ghcr.io/${OWNER,,}/mhgurecomp-builder:$REVISION"
   ```

   If you are using a fork, replace `morerokk/MHGURecomp` before running this
   block. The image owner must match the source repository owner: publishing
   from a fork does not create an upstream image. Upstream needs a successful
   publication of its own after the PR is merged.

8. Download the image for that same SHA:

   ```bash
   docker pull "$IMAGE"
   ```

9. Build both packages from the repository root:

   ```bash
   bash tools/build-linux-release.sh --game "/absolute/path/to/data" \
     --version 0.13.0 --jobs 2 --image "$IMAGE" --skip-image-build
   ```

   Point `--game` to a folder containing `exefs/main`, `exefs/sdk`, and
   `romfs/`. The script generates the game C once, then builds each target
   separately. The version here is the package version; change it if you
   deliberately build a different release.

10. Check the package hashes:

   ```bash
   (cd dist && sha256sum -c SHA256SUMS)
   ```

**Use the full SHA of a run that published an image, not just the latest
checkout SHA.** Documentation-only pushes do not trigger this workflow, so
they do not create image tags. The moving `linux-amd64` tag is useful as a
convenience tag, but it does not identify a fixed source revision; use the
full-SHA tag to select the matching source and builder.

If the tag is missing, check the publication job and the SHA you copied.
For an access error, ask the image owner to check the package's visibility.
You can always build the tools image locally instead. There is no reason
to send your dump to a maintainer or upload it to troubleshoot a pull failure.

Before starting a build, commit or restore any tracked changes. The script
exports the current commit with `git archive`, so untracked files and previous
build folders are not included in the source it compiles.

## Build the tools image locally

You can build the same tools image locally if GHCR is unavailable or there
is no suitable public image. This route needs neither GitHub Actions nor
GHCR access or a GitHub token. Clone the repository, select the revision you
want to build, and run the following from its root:

```bash
bash tools/build-linux-release.sh --game "/absolute/path/to/data" \
  --version 0.13.0 --jobs 2
```

Without `--skip-image-build`, the script builds the tools image before
compiling both packages. As with the published-image route, tracked files
must be clean so the source export matches the selected commit.

## Package contents and privacy

The commands above produce:

- `dist/Linux-MHGURecomp.0.13.0.tar.gz`
- `dist/LinuxARM64-MHGURecomp.0.13.0.tar.gz`
- `dist/SHA256SUMS`

Each archive contains the runtime, game library, updater, licenses, and
pipelines. Although it excludes your raw dump, saves, generated C, and donor
content, its `mhgugame.so` library contains game-derived code. Building an
archive does not give you permission to distribute that code: the project's
license does not cover the game or its recompiled code. Keep these builds
private and do not upload them to CI or GHCR.

Your dump is mounted read-only into the local build container, never added
to an image layer. The image's build context allows only selected files under
`tools/`, and only the local release command compiles your game library.
Neither GitHub Actions nor GHCR receives your dump or generated game code.

## Test the packages

1. Extract the x86-64 archive into a new folder on your PC.
2. Put your own `exefs` and `romfs` folders in its `data/` folder.
3. Start `mhgurecomp` from the extracted folder.
4. Extract the ARM64 archive into a new folder on your Linux ARM64 device.
5. Put your own `exefs` and `romfs` folders in its `data/` folder.
6. Start `mhgurecomp` on that device.

Back up your saves before testing, then check graphics, audio, controls,
and save loading on both targets. Saves still default to
`~/.local/share/MHGURecomp/save/`; setting `MHGU_HOME` does not move them.

Start the runtime directly for the first test rather than using the updater.
The updater still contacts the original repository, not your fork, and this
workflow does not publish a game release for it to download.

## Docker on Fedora and SELinux

The same Docker commands work on Fedora. With rootful Docker, the script
uses your host UID, GID, and supplementary groups; rootless Docker uses its
default user mapping instead. Make sure your host user can read the dump,
since access through supplementary groups alone may not work in rootless
mode. You should still run the build command without `sudo`.

On an SELinux host, the work and output mounts use `:Z`, while the dump uses
`:ro,z` for shared, read-only access. These options relabel the folders you
select, so use a dedicated dump folder rather than mounting your whole home
directory. The script neither disables SELinux nor requests a privileged
container.

## Cache and failures

The ignored `.linux-release/` folder holds the build's sources, objects, and
generated C. After a release build it contains private game-derived files,
so do not upload or share it. Each source commit and builder image gets a
separate cache; your existing `build-arm64/` and `obj-arm64/` are left alone.

If either target fails, the command stops without copying new packages to
`dist/`. Older packages may still be there, so use the command's exit status
and the hash check after a successful run rather than treating their presence
as proof of success. Rerunning the same command reuses compatible dependency
builds, but generates fresh game C on every release run.

Only local Docker contexts are supported because the bind mounts refer to
files on your host. Dump and checkout paths may contain spaces, but not
colons or newlines. Run only one build at a time in a given checkout.

## CI scope

The Linux builder checks both targets without game files, compiling the
runtime and updater and running public-code tests. The builder remains
`linux/amd64` in both jobs, with QEMU used for the ARM64 checks. These jobs
do not produce playable releases or test graphics and gameplay.

The settings-panel navigation test is an exception to the required checks:
the workflow currently treats it as advisory, so a failure produces a warning
rather than failing the job. A green run therefore does not, by itself, prove
that this particular test passed. The other build, architecture, ABI, and
regression checks remain required.

## Maintainer: Actions and GHCR after merge

The following setup is for repository maintainers. Users downloading a
public image do not need to configure Actions or GHCR. Before approving a
fork's run, review the workflow; GitHub may require
[manual approval for fork PRs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks).
PR runs need no game files and do not publish images.

### Permit the workflow

Actions is normally enabled, but repository or organization policies may
restrict it. Merging the PR does not override those settings.

1. Open the repository's **Settings → Actions → General**.
2. Check the [Actions permissions](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository).
3. Permit the four actions that this workflow uses:
   `actions/checkout`, `docker/setup-buildx-action`,
   `docker/build-push-action`, and `docker/login-action`.
   Keep their full-SHA pins in the workflow.
4. If **Linux builder** is disabled, open it under **Actions**.
5. Select **Enable workflow**.

GitHub's [workflow enable instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)
cover this process in more detail. There is no need to enable global write
access or create a personal access token: the publication job already
requests its own `packages: write` permission and uses the repository's
`GITHUB_TOKEN`.

### Run the first upstream publication

When Actions permits it, merging this PR into `master` should start a run:
the merge includes files covered by the workflow's path filters. Both
architecture jobs must pass before publication begins. GitHub documents
the details in its [trigger rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

If no run starts after the merge, use the manual trigger:

1. Open **Actions → Linux builder**.
2. Select **Run workflow**.
3. Select `master`.
4. Select **Run workflow** to start it.
5. Wait for both architecture jobs and **Publish the tools image** to pass.

The manual trigger requires write access, and the workflow file must already
exist on the default branch for the control to appear. See
[Manually running a workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
if it is missing. Documentation-only pushes do not start this workflow.

### Make the image public

The workflow publishes `ghcr.io/<owner>/mhgurecomp-builder`, using the
repository owner's name in lowercase, with both a full source-SHA tag and
the moving `linux-amd64` tag. A new GHCR package is private by default even
when its repository is public, so check its visibility before directing
users to it. GitHub's [Container registry guide](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
explains how these packages work.

1. Open the repository owner's **Packages** page.
2. Select **mhgurecomp-builder**.
3. Open **Package settings**.
4. Under **Danger Zone**, select **Change visibility**.
5. Select **Public** and confirm the change.

Review the image before making it public: anyone will be able to download
its contents, and a public package cannot be made private again. Organization
policies may also restrict visibility changes; see
[package access and visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).

Verify an anonymous pull with an empty temporary Docker configuration:

```bash
OWNER=morerokk
read -r -p "Full source SHA from the upstream publication: " REVISION
IMAGE="ghcr.io/${OWNER,,}/mhgurecomp-builder:$REVISION"
ANONYMOUS_CONFIG=$(mktemp -d)
docker --config "$ANONYMOUS_CONFIG" --host unix:///var/run/docker.sock pull "$IMAGE"
rm -r "$ANONYMOUS_CONFIG"
```

This example uses the standard local Docker socket. If you use rootless
Docker, substitute its configured local socket; for a fork, also change
`OWNER` to the fork's owner. Only the tools image belongs in this registry,
not a game dump, generated game C, or playable packages.

## Image reproducibility

The image keeps its APT package manifests and hashes under `/opt/mhgu/`.
These record what was downloaded, but Ubuntu's repositories can change,
so rebuilding the image later is not guaranteed to produce identical bytes.
