# Development

This page covers local development, testing, dependency auditing, and release
builds. End users should install PromptMeld from the
[latest GitHub release](https://github.com/an1uk/promptmeld-windows/releases/latest).

## Set up the development environment

Install Python 3.12 x64 from
[python.org](https://www.python.org/downloads/) and enable the Python launcher.
Then run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
.\scripts\run.ps1
```

## Test

Run the test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run the dependency licence audit directly:

```powershell
.\.venv\Scripts\python.exe .\tools\check_licenses.py
```

## Build the portable application

```powershell
.\scripts\build.ps1
```

The output is written to `dist\PromptMeld`. `PromptMeld.exe` is the only
executable users should launch. Keep the `_internal` directory beside it; that
directory contains the automation companion and required runtime files.

PromptMeld uses one-folder packaging because it starts faster and is easier for
antivirus products to inspect than a self-extracting one-file executable.

Each build audits every declared and transitive package against
`tools\dependency-license-policy.json`. After packaging, it checks the actual
Qt DLLs and plugins, copies applicable licence texts into `LICENSES`, and stops
if an unreviewed dependency or binary appears.

## Build the installer

```powershell
.\scripts\build-installer.ps1
```

The installer is written to:

```text
dist\installer\PromptMeld-Setup-v<major>.<minor>.<patch>.exe
```

Building the installer requires
[Inno Setup 6](https://jrsoftware.org/isinfo.php). The installed application
does not. The three-part semantic version in `pyproject.toml` is the single
release version source. It is written to the packaged `VERSION` file, used in
the installer filename, and embedded in the Windows version resource with a
fourth numeric component of zero.

Every new distributable build must have a newer version than the preceding
build. Update `project.version` in `pyproject.toml` before building: increment
the patch number for fixes, the minor number for compatible features, or the
major number for incompatible changes. The installer build refuses to
overwrite an installer with the same version by default. Use
`-AllowSameVersion` only when deliberately reproducing an unchanged release,
never for a build containing new code or documentation.

## Release checklist

1. Increase `project.version` in `pyproject.toml` and confirm it is newer than
   the latest published or previously built version.
2. Run the complete test suite.
3. Run the dependency licence audit.
4. Build the application and installer from a clean source checkout.
5. Smoke-test installation, launch, selected-text capture, fallback, and
   uninstallation.
6. If signing is available, sign the application executables, installer, and
   uninstaller and verify their Authenticode signatures.
7. Confirm the installer is named exactly
   `PromptMeld-Setup-v<major>.<minor>.<patch>.exe`.
8. Create a matching `v<major>.<minor>.<patch>` tag and a non-draft,
   non-prerelease GitHub release, then attach that single installer.
9. Confirm GitHub reports a SHA-256 digest for the uploaded asset and that the
   release is returned by the repository's latest stable release endpoint.

## Publish changes to GitHub

Repository publication uses the dedicated `build\github-publish` checkout so
development changes cannot accidentally be mixed with a stale branch or local
build output. The mandatory workflow and safety checks are recorded in the
root `AGENTS.md`, which is also loaded automatically by Codex sessions working
in this repository.

In summary: authenticate with `gh`, fetch the latest `origin/main` in the
publication checkout, create a fresh `codex/<description>` branch, transfer
only the verified files, stage explicit paths, run the staged diff checks,
push with upstream tracking, open a draft pull request, and read the resulting
pull request back from GitHub. Never commit `build`, `dist`, or installer
artifacts; attach a verified installer to the corresponding GitHub release.
