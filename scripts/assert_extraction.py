#!/usr/bin/env python3
"""Assert that Renovate extracted every Pants code path this repository covers.

Reads the JSON report written by `renovate --platform=local` with
`RENOVATE_REPORT_TYPE=file`, and checks one expectation per code path. Exits
non-zero with a diff of what is missing, so a regression in the pants manager
fails this repository's workflow instead of hiding in a log.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# (manager, packageFile, depName, depType) tuples that must be present.
EXPECTED: list[tuple[str, str, str, str]] = [
    # inline python_requirement, in all its shapes
    ("pants", "inline/BUILD.pants", "click", "python_requirement"),
    ("pants", "inline/BUILD.pants", "requests", "python_requirement"),
    ("pants", "inline/BUILD.pants", "urllib3", "python_requirement"),
    ("pants", "inline/BUILD.pants", "types-protobuf", "python_requirement"),
    ("pants", "inline/BUILD.pants", "packaging", "python_requirement"),
    # the same dist pinned once per resolve: two separate dependencies
    ("pants", "inline/BUILD.pants", "pytest", "python_requirement"),
    # a generator source, named by the default and by the `source` field
    ("pants", "default-source/requirements.txt", "charset-normalizer", "python_requirements"),
    ("pants", "default-source/requirements.txt", "idna", "python_requirements"),
    ("pants", "named-source/prod-requirements.txt", "certifi", "python_requirements"),
    # fields other than name/requirements/source are ignored, but the source
    # itself is still extracted
    ("pants", "inline/ignored-requirements.txt", "attrs", "python_requirements"),
    # PEP 621, including a PEP 735 dependency group
    ("pants", "pep621/pyproject.toml", "typing-extensions", "project.dependencies"),
    ("pants", "pep621/pyproject.toml", "pytest-mock", "dependency-groups"),
    # Poetry, including a dependency group
    ("pants", "poetry/pyproject.toml", "tenacity", "dependencies"),
    ("pants", "poetry/pyproject.toml", "ruff", "dev"),
    # uv reads `[tool.uv] dev-dependencies`, and the file's own `[project]`
    ("pants", "uv/pyproject.toml", "httpx", "project.dependencies"),
    ("pants", "uv/pyproject.toml", "pytest-asyncio", "tool.uv.dev-dependencies"),
    # an unrelated `[tool.poetry-*]` table must not route the file to Poetry,
    # which would drop the uv dependencies
    ("pants", "poetry-prefixed-tool/pyproject.toml", "pyyaml", "project.dependencies"),
    (
        "pants",
        "poetry-prefixed-tool/pyproject.toml",
        "coverage",
        "tool.uv.dev-dependencies",
    ),
    # a build file named by `build_patterns`
    ("pants", "custom-build-file-name/pants_targets.py", "rich", "python_requirement"),
    # a VCS requirement keeps its git datasource
    ("pants", "vcs/BUILD.pants", "black", "python_requirement"),
    # a Poetry project with a lock file is left to the poetry manager, which can
    # regenerate the lock file
    ("poetry", "poetry-locked/pyproject.toml", "jinja2", "dependencies"),
    # a requirements file with hashes is left to pip_requirements, which
    # refreshes them with `hashin`
    ("pip_requirements", "hashed/hashed-requirements.txt", "six", ""),
]

# (manager, packageFile) pairs that must NOT appear.
FORBIDDEN: list[tuple[str, str]] = [
    # `supersedesManagers` drops the other manager for a file pants produced
    ("pip_requirements", "default-source/requirements.txt"),
    ("pep621", "pep621/pyproject.toml"),
    ("poetry", "poetry/pyproject.toml"),
    # ...and drops pants for the file whose lock file it cannot regenerate
    ("pants", "poetry-locked/pyproject.toml"),
    # pants never claims a hashed requirements file
    ("pants", "hashed/hashed-requirements.txt"),
]


def main(report_path: str) -> int:
    report = json.loads(Path(report_path).read_text())
    repositories = report.get("repositories", {})

    found: set[tuple[str, str, str, str]] = set()
    lock_claims: list[tuple[str, str, list[str]]] = []
    pytest_pins = 0

    for repo in repositories.values():
        for manager, package_files in (repo.get("packageFiles") or {}).items():
            for package_file in package_files:
                name = package_file["packageFile"]
                if manager == "pants" and package_file.get("lockFiles"):
                    lock_claims.append((manager, name, package_file["lockFiles"]))
                for dep in package_file.get("deps") or []:
                    dep_name = dep.get("depName")
                    if dep_name is None:
                        continue  # interpreter constraint, not a requirement
                    found.add((manager, name, dep_name, dep.get("depType") or ""))
                    if (
                        manager == "pants"
                        and name == "inline/BUILD.pants"
                        and dep_name == "pytest"
                    ):
                        pytest_pins += 1

    failures: list[str] = []

    for expectation in EXPECTED:
        if expectation not in found:
            failures.append(f"missing: {expectation}")

    for manager, package_file in FORBIDDEN:
        if any(m == manager and f == package_file for m, f, _, _ in found):
            failures.append(f"should have been superseded: ({manager}, {package_file})")

    # Both targets that pin pytest have to be extracted, or only one of them
    # would ever be updated.
    if pytest_pins != 2:
        failures.append(
            f"expected 2 pytest dependencies in inline/BUILD.pants, found {pytest_pins}"
        )

    # This manager has no `updateArtifacts`, so it must never claim a lock file.
    for manager, package_file, lock_files in lock_claims:
        failures.append(f"pants claimed lock files it cannot update: {package_file} -> {lock_files}")

    print(f"checked {len(EXPECTED)} expectations against {len(found)} extracted dependencies")
    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        print("\nExtracted:")
        for entry in sorted(found):
            print(f"  {entry}")
        return 1

    print("all expectations met")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: assert_extraction.py <report.json>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
