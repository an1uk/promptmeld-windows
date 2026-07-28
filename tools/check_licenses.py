from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import sys
import tomllib
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_RELATIVE_PATH = Path("tools") / "dependency-license-policy.json"
POLICY_PATH = PROJECT_ROOT / POLICY_RELATIVE_PATH
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"


@dataclass
class AuditedDistribution:
    distribution: importlib.metadata.Distribution
    scopes: set[str] = field(default_factory=set)

    @property
    def name(self) -> str:
        return canonicalize_name(self.distribution.metadata["Name"])

    @property
    def version(self) -> str:
        return self.distribution.version


@dataclass
class AuditResult:
    packages: dict[str, AuditedDistribution]
    errors: list[str]


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_declared_requirements(
    path: Path = PYPROJECT_PATH,
) -> dict[str, list[Requirement]]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    groups = {
        "runtime": document.get("project", {}).get("dependencies", []),
        "dev": (
            document.get("project", {})
            .get("optional-dependencies", {})
            .get("dev", [])
        ),
        "build": document.get("build-system", {}).get("requires", []),
    }
    parsed: dict[str, list[Requirement]] = {}
    for scope, entries in groups.items():
        parsed[scope] = [Requirement(entry) for entry in entries]
    return parsed


def _requirement_applies(requirement: Requirement) -> bool:
    if requirement.marker is None:
        return True
    environment = default_environment()
    environment["extra"] = ""
    return requirement.marker.evaluate(environment)


def _license_evidence(distribution: importlib.metadata.Distribution) -> str:
    metadata = distribution.metadata
    values = [
        metadata.get("License-Expression", ""),
        metadata.get("License", ""),
    ]
    values.extend(
        classifier
        for classifier in metadata.get_all("Classifier", [])
        if classifier.startswith("License ::")
    )
    return "\n".join(value for value in values if value)


def audit_environment(
    project_root: Path = PROJECT_ROOT,
    policy: dict[str, Any] | None = None,
) -> AuditResult:
    policy = policy or load_policy(project_root / POLICY_RELATIVE_PATH)
    declared = load_declared_requirements(project_root / PYPROJECT_PATH.name)
    package_policy = {
        canonicalize_name(name): value
        for name, value in policy["packages"].items()
    }
    packages: dict[str, AuditedDistribution] = {}
    errors: list[str] = []
    queue: deque[tuple[Requirement, str, str]] = deque()
    processed: set[tuple[str, str]] = set()

    for scope, requirements in declared.items():
        for requirement in requirements:
            queue.append((requirement, scope, "pyproject.toml"))

    while queue:
        requirement, scope, parent = queue.popleft()
        if not _requirement_applies(requirement):
            continue
        name = canonicalize_name(requirement.name)
        pair = (name, scope)
        if pair in processed:
            continue
        processed.add(pair)

        try:
            distribution = importlib.metadata.distribution(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            errors.append(
                f"{parent} requires {requirement}, but it is not installed."
            )
            continue

        if requirement.specifier and not requirement.specifier.contains(
            distribution.version,
            prereleases=True,
        ):
            errors.append(
                f"{parent} requires {requirement}, but "
                f"{distribution.metadata['Name']} {distribution.version} "
                "is installed."
            )

        audited = packages.setdefault(
            name,
            AuditedDistribution(distribution),
        )
        audited.scopes.add(scope)

        requirements = distribution.requires or []
        for child_text in requirements:
            try:
                child = Requirement(child_text)
            except InvalidRequirement:
                errors.append(
                    f"{distribution.metadata['Name']} {distribution.version} "
                    f"contains an invalid dependency declaration: {child_text}"
                )
                continue
            if _requirement_applies(child):
                queue.append(
                    (
                        child,
                        scope,
                        f"{distribution.metadata['Name']} {distribution.version}",
                    )
                )

    for name, audited in sorted(packages.items()):
        approved = package_policy.get(name)
        display_name = audited.distribution.metadata["Name"]
        if approved is None:
            errors.append(
                f"{display_name} {audited.version} has no reviewed entry in "
                "tools/dependency-license-policy.json."
            )
            continue

        unapproved_scopes = audited.scopes - set(approved.get("scopes", []))
        if unapproved_scopes:
            errors.append(
                f"{display_name} {audited.version} is now used in unreviewed "
                f"scope(s): {', '.join(sorted(unapproved_scopes))}."
            )

        evidence = _license_evidence(audited.distribution)
        markers = approved.get("license_markers", [])
        matches = [
            marker.casefold() in evidence.casefold() for marker in markers
        ]
        marker_mode = approved.get("marker_mode", "all")
        marker_match = (
            any(matches) if marker_mode == "any" else all(matches)
        )
        if not markers or not marker_match:
            errors.append(
                f"{display_name} {audited.version} no longer reports the "
                "reviewed licence evidence. Observed metadata: "
                f"{evidence.strip() or '<none>'}"
            )

    for asset in policy.get("asset_checks", []):
        asset_path = project_root / asset["path"]
        if not asset_path.is_file():
            errors.append(f"Reviewed asset licence is missing: {asset_path}")
            continue
        contents = asset_path.read_text(encoding="utf-8")
        for marker in asset.get("license_markers", []):
            if marker.casefold() not in contents.casefold():
                errors.append(
                    f"{asset['path']} no longer contains reviewed licence "
                    f"marker: {marker}"
                )

    for static_license in policy.get("static_license_checks", []):
        license_path = project_root / static_license["path"]
        if not license_path.is_file():
            errors.append(f"Required licence text is missing: {license_path}")
            continue
        digest = hashlib.sha256(license_path.read_bytes()).hexdigest()
        if digest != static_license["sha256"].casefold():
            errors.append(
                f"{static_license['path']} does not match the reviewed "
                "official licence text."
            )

    return AuditResult(packages, errors)


def _is_license_file(path: Path) -> bool:
    lowered_parts = [part.casefold() for part in path.parts]
    name = path.name.casefold()
    return (
        "licenses" in lowered_parts
        or name.startswith(("license", "copying", "notice"))
    )


def _safe_license_name(path: Path) -> str:
    return "__".join(
        part.replace("..", "_") for part in path.parts if part not in {".", ".."}
    )


def _copy_distribution_licenses(
    audited: AuditedDistribution,
    destination: Path,
) -> int:
    copied = 0
    seen: set[Path] = set()
    for entry in audited.distribution.files or []:
        relative = Path(str(entry))
        if not _is_license_file(relative):
            continue
        source = Path(audited.distribution.locate_file(entry))
        if not source.is_file():
            continue
        resolved = source.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        target = destination / _safe_license_name(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def collect_release_licenses(
    project_root: Path,
    destination: Path,
    policy: dict[str, Any],
    result: AuditResult,
) -> list[str]:
    errors: list[str] = []
    destination.mkdir(parents=True, exist_ok=True)
    static_licenses = project_root / "LICENSES"
    if not static_licenses.is_dir():
        return [f"Static licence directory is missing: {static_licenses}"]

    for source in static_licenses.iterdir():
        target = destination / source.name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)

    shutil.copy2(project_root / "LICENSE", destination.parent / "LICENSE")
    shutil.copy2(
        project_root / "THIRD_PARTY_NOTICES.md",
        destination.parent / "THIRD_PARTY_NOTICES.md",
    )

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(
            python_license,
            destination / f"Python-{sys.version_info.major}.{sys.version_info.minor}.txt",
        )
    else:
        errors.append(f"Python licence file is missing: {python_license}")

    lucide_license = (
        project_root
        / "src"
        / "promptmeld"
        / "resources"
        / "icons"
        / "lucide"
        / "LICENSE"
    )
    shutil.copy2(lucide_license, destination / "Lucide-Icons.txt")

    package_policy = {
        canonicalize_name(name): value
        for name, value in policy["packages"].items()
    }
    report_lines = [
        "PromptMeld dependency licence audit",
        "",
        f"Python {sys.version.split()[0]} | runtime | PSF-2.0",
    ]
    for name, audited in sorted(result.packages.items()):
        approved = package_policy[name]
        scopes = ", ".join(sorted(audited.scopes))
        selected = approved["selected_license"]
        report_lines.append(
            f"{audited.distribution.metadata['Name']} {audited.version} | "
            f"{scopes} | {selected}"
        )
        if not approved.get("collect_license_files", False):
            continue
        package_destination = (
            destination
            / "packages"
            / f"{name}-{audited.version}"
        )
        copied = _copy_distribution_licenses(
            audited,
            package_destination,
        )
        if copied == 0:
            errors.append(
                f"No licence files could be collected for "
                f"{audited.distribution.metadata['Name']} {audited.version}."
            )

    report_lines.append("Lucide Icons | runtime asset | ISC and MIT")
    (destination / "DEPENDENCY_AUDIT.txt").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )
    return errors


def check_bundle(
    bundle_root: Path,
    policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    bundle_policy = policy["bundle_policy"]
    files = [path for path in bundle_root.rglob("*") if path.is_file()]
    names = {path.name.casefold(): path for path in files}

    for forbidden in bundle_policy["forbidden_file_names"]:
        found = names.get(forbidden.casefold())
        if found is not None:
            errors.append(
                f"Forbidden or unreviewed GPL-only Qt component bundled: {found}"
            )

    allowed_frameworks = {
        name.casefold()
        for name in bundle_policy["allowed_qt_framework_binaries"]
    }
    for path in files:
        if (
            path.suffix.casefold() == ".dll"
            and path.name.casefold().startswith("qt6")
            and path.name.casefold() not in allowed_frameworks
        ):
            errors.append(f"Unreviewed Qt framework binary bundled: {path}")

    allowed_plugins = {
        name.casefold()
        for name in bundle_policy["allowed_qt_plugin_binaries"]
    }
    for path in files:
        lowered_parts = [part.casefold() for part in path.parts]
        if (
            path.suffix.casefold() == ".dll"
            and "plugins" in lowered_parts
            and path.name.casefold() not in allowed_plugins
        ):
            errors.append(f"Unreviewed Qt plugin binary bundled: {path}")

    reviewed_dlls = (
        allowed_frameworks
        | allowed_plugins
        | {
            name.casefold()
            for name in bundle_policy["allowed_native_runtime_binaries"]
        }
    )
    for path in files:
        if (
            path.suffix.casefold() == ".dll"
            and path.name.casefold() not in reviewed_dlls
        ):
            errors.append(f"Unreviewed native runtime DLL bundled: {path}")

    for relative in bundle_policy["required_release_files"]:
        required = bundle_root / Path(relative)
        if not required.is_file():
            errors.append(f"Required release notice is missing: {required}")
    return errors


def _print_result(
    result: AuditResult,
    policy: dict[str, Any],
) -> None:
    package_policy = {
        canonicalize_name(name): value
        for name, value in policy["packages"].items()
    }
    print("Dependency licence audit:")
    for name, audited in sorted(result.packages.items()):
        approved = package_policy.get(name, {})
        licence = approved.get("selected_license", "UNREVIEWED")
        scopes = ",".join(sorted(audited.scopes))
        print(
            f"  {audited.distribution.metadata['Name']} "
            f"{audited.version}: {licence} [{scopes}]"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enforce PromptMeld's reviewed dependency licence policy."
    )
    parser.add_argument(
        "--collect-licenses",
        type=Path,
        help="Copy release licence files into this directory.",
    )
    parser.add_argument(
        "--check-bundle",
        type=Path,
        help="Check the contents and notices of a packaged release.",
    )
    args = parser.parse_args(argv)

    policy = load_policy()
    result = audit_environment(PROJECT_ROOT, policy)
    errors = list(result.errors)
    _print_result(result, policy)

    if args.collect_licenses and not errors:
        errors.extend(
            collect_release_licenses(
                PROJECT_ROOT,
                args.collect_licenses.resolve(),
                policy,
                result,
            )
        )
    if args.check_bundle:
        errors.extend(check_bundle(args.check_bundle.resolve(), policy))

    if errors:
        print("\nLicence audit failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("\nLicence audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
