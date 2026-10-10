# Contributing to Phone Webcam

Thank you for considering a contribution! This document covers the local dev
setup, commit conventions, release process, and where the CI pipeline will be
described.

## How to contribute

- **Bug reports** - open an issue on GitLab describing what you expected, what
  happened, and how to reproduce it. Include your distribution and desktop
  environment, the phone model and Android version, the scrcpy version, and the
  Phone Webcam version (`rpm -q phone-webcam` or `dpkg -s phone-webcam`). The
  output of `phone-webcam --check` and the log from the window (the **Copy**
  button above it) help a lot.
- **Feature requests** - open an issue first to discuss the idea before investing
  time in an MR.
- **Merge requests** - fork the repository, branch from `main`, and open an MR.
  All tests must pass, and commits must follow the
  [Conventional Commits](#commit-messages) format below.

## Dev environment

Requires: `uv`, `git`, and Python 3.14, which `uv` fetches for you. The
devcontainer has everything pre-installed and is the easiest way to get started.
To run the app for real you also need the system tools it checks for: scrcpy,
adb, ffmpeg, polkit and the `v4l2loopback` kernel module. The app's own
dependency check lists what is missing and the command to install it.

```bash
git clone https://gitlab.com/griffin-web-studio/garage/phone-webcam.git
cd phone-webcam
```

Then either open in the devcontainer, or set up manually:

```bash
# Install/update dependencies and activate the venv
uv sync --all-extras

# Install pre-commit hooks (commit linting + formatters)
pre-commit install
pre-commit install --hook-type commit-msg
```

`scripts/setup_settings.sh` automates the hooks. If you don't have `uv` yet,
install it via the [official installer](https://docs.astral.sh/uv/getting-started/installation/)
or through `pipx install uv`.

Only Linux is supported, because the virtual camera is a Linux kernel module.

### Running the app from source

```bash
uv run python run.py                  # the app
uv run python run.py --check          # the dependency checks, without a window
uv run python run.py --simulate-missing scrcpy,ffmpeg   # see a missing tool
```

`.vscode/launch.json` has debug configurations for the first two.

### The devcontainer

The container shares your phone's USB bus, but it cannot load the kernel module,
because a container uses the host's kernel and has no polkit agent. So the
virtual camera has to be created on the host (the app does that for you when you
run it there), and the container is best for editing, the tests and building the
packages. To try the whole thing, run the app on the host.

Two details of `.devcontainer/devcontainer.json` to know about:

- It passes an NVIDIA GPU through with CDI and refuses to start when the host has
  no CDI spec. If you have no NVIDIA GPU, remove the `initializeCommand`, the
  `nvidia.com/gpu=all` device and the Mesa environment variables.
- It reads `.devcontainer/.env` into the container, and Podman refuses to start
  if that file is missing. It is not committed, so create it yourself. An empty
  file is fine.

## Running tests

```bash
uv run pytest
```

Extra arguments go to pytest, for example `uv run pytest -k pipeline -x`.

- The tests never talk to a real phone, adb, scrcpy or pkexec. `tests/conftest.py`
  isolates your saved preferences and reports no phone, and the tests that need
  more fake the process calls.
- A few tests run the real `ffmpeg` to draw SVG covers. They skip themselves when
  ffmpeg is missing or built without SVG support.
- The GUI itself is not tested automatically. Check changes to `phone_webcam/web/`
  by running the app, and keep `web/types.d.ts` in step with `api.py` by hand.

## Code style

- **Python** is formatted with Black at 80 columns, and the pre-commit hook does
  it for you. Sections in a file are separated with a label in the same style as
  the existing ones, for example
  `# ─────────────────────────────────────────| Section Name |──`, fitted to 80
  columns.
- **The interface** is plain HTML, CSS and JavaScript, with no build step and no
  framework. JavaScript is typed with JSDoc and `// @ts-check`, and `jsconfig.json`
  turns on strict checking in editors. Use two spaces and Prettier's defaults
  (`.prettierrc.json`).
- **Text** in code, comments and documents is British English, and uses plain
  hyphens, not long dashes. Comments say why, not what.
- `.editorconfig` sets the basics, so most editors pick it up on their own.

The pre-commit hooks also fix trailing whitespace and final newlines, and check
YAML.

## How the code is laid out

`docs/architecture.md` explains the whole thing. In short, everything is in
`phone_webcam/`:

| Path                 | What it holds                                              |
| -------------------- | ---------------------------------------------------------- |
| `main.py`, `deps.py` | Start-up and the dependency checks.                        |
| `api.py`             | What the page can call, and how events reach it.           |
| `webcam.py`          | The controller, one run from start to stop.                |
| `pipeline.py`        | Reading, turning and writing frames.                       |
| `preview.py`, `slate.py` | The live preview and the cover image.                  |
| `web/`               | The interface.                                             |
| `slates/`, `assets/` | The default cover image and the app icon.                  |
| `tests/`             | One test module for each module above.                     |
| `packaging/`, `scripts/` | Desktop files, specs and the build scripts.            |

### Adding a setting

A setting that the user can change touches the same places each time, so use an
existing one as a pattern, such as the frame rate:

1. Add the field and its validation to `phone_webcam/settings.py`, with the
   allowed choices. Bad values must fall back to the default one by one.
2. Use it in `webcam.py` and, if it affects frames, `pipeline.py`. Decide whether
   it can change while running, and if not, lock it in `setState` in `web/app.js`.
3. Expose it in `api.py`, and save it through `config.update_prefs` so it does
   not overwrite other saved choices.
4. Add the control to `web/app.html`, wire it up in `web/app.js`, and describe
   the new call and event in `web/types.d.ts`.
5. Test each layer, and update the README's settings table and the user guide.

## Commit messages

This project follows [Conventional Commits](https://www.conventionalcommits.org/).
The `commitlint` pre-commit hook enforces this on every commit.

```
<type>(<scope>): <subject>

feat(webcam):   add the privacy shutter
fix(deps):      find Qt libraries in a compiled build
perf(pipeline): skip copying frames that are not turned
refactor(api):  extract the event queue
build(rpm):     add a spec and a script that builds an .rpm
docs:           explain the cover image
chore:          bump black to 26.10.0
test:           cover the camera switch revert
```

Types that appear in `CHANGELOG.md`: `feat`, `fix`, `perf`, `refactor`.
Types excluded from the changelog (`build`, `chore`, `ci`, `docs`, `style`,
`test`) are not user-facing.

Breaking changes - append `!` to the type or add a `BREAKING CHANGE:` footer:

```
feat!: save settings in a new file format

BREAKING CHANGE: prefs.json is read from a different place, old files are ignored
```

## Cutting a release

Releases are driven by `cz bump`, which reads commits since the last tag,
determines the next version, updates version files, and creates the tag.

### Stable release

```bash
cz bump
git push origin main --follow-tags
```

`cz bump` will:

1. Determine the next version from commits (`feat` to minor, `fix`/`perf` to
   patch, `BREAKING CHANGE` to major)
2. Update `version` in `pyproject.toml` (both places), and the version in the
   README's title and its release link
3. Run `uv lock`, so `uv.lock` carries the new version in the same commit
4. Prepend an entry to `CHANGELOG.md`
5. Commit and tag as `vX.Y.Z`

The very first `cz bump`, when there are no tags yet, asks "Is this the first tag
created?". Answer yes.

### Pre-release

Accepted pre-release types: `alpha`, `beta`, `rc`.

```bash
cz bump --prerelease alpha   # to v1.0.0-alpha.0
cz bump --prerelease alpha   # to v1.0.0-alpha.1  (subsequent alpha)
cz bump --prerelease beta    # to v1.0.0-beta.0
cz bump --prerelease rc      # to v1.0.0-rc.0
cz bump                      # to v1.0.0           (promote to stable)
git push origin main --follow-tags
```

### Manual override (if needed)

```bash
cz bump --increment MAJOR     # force a major bump regardless of commits
cz bump --increment MINOR
cz bump --increment PATCH
```

### After tagging

Build the binary and the packages from the tagged commit, as in
[Building locally](#building-locally), and attach them to the release. Once the
pipeline exists it will do this.

### Tag format

| Tag                | Channel | Notes                            |
| ------------------ | ------- | -------------------------------- |
| `v1.0.0-alpha.0`   | alpha   | early testing, may be unstable   |
| `v1.0.0-beta.0`    | beta    | feature-complete, bugfixes only  |
| `v1.0.0-rc.0`      | rc      | release candidate                |
| `v1.0.0`           | stable  | full release                     |

## CI pipeline

The pipeline is being set up. This section will describe its jobs, its triggers
and how releases are published once it exists.

## Building locally

Everything is run from the project root, and the results land in `dist/`. The
devcontainer has all of the tools: `gcc`, `patchelf`, `rpm`, `lintian` and the
rest.

| Script                 | Result                                     |
| ---------------------- | ------------------------------------------ |
| `scripts/build.sh`     | `dist/phone-webcam`, the binary            |
| `scripts/build-deb.sh` | `dist/phone-webcam_<version>_amd64.deb`    |
| `scripts/build-rpm.sh` | `dist/phone-webcam-<version>-1.x86_64.rpm` |

```bash
bash scripts/build.sh                 # produces dist/phone-webcam
./dist/phone-webcam --check           # smoke-test the binary
bash scripts/build-deb.sh
bash scripts/build-rpm.sh
```

The packages need the binary and build it first if it is missing. The first
build takes a few minutes, later ones are quicker.

Keep these in mind, they are explained in `docs/packaging.md`:

- The version and the licence come from `pyproject.toml`.
- The binary unpacks itself once into
  `~/.cache/Griffin Web Studio/Phone Webcam/<version>` and reuses that. A rebuild
  with the same version therefore keeps running the old files until that folder
  is deleted, so bump the version for a release.
- The binary must not be stripped, it is a launcher with the app appended to it.
  The packaging scripts leave it alone, keep it that way.
- The system packages a package depends on come from `phone_webcam/deps.py`, the
  same table the app's own dependency check uses. Change them there.
- The binary needs a glibc at least as new as the symbols it was built with.
  Built in the Debian 13 devcontainer that is 2.38, which the packages declare.
  To support older systems, build on one of them and check the number again.
- Nuitka warns that PyQt6 is not perfect, in particular Qt threading. The binary
  has been run on a real desktop with the clipboard and the preview, which cross
  threads, without trouble. If that ever changes, PySide6 is the binding Nuitka
  recommends.

## Documentation

The user-facing documentation is the [README](README.md) and `docs/`. When you
change what the app does, change those in the same MR. The index in
`docs/README.md` says what each page is for.
