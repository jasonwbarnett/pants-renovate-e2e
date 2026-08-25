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

# (manager, packageFile, depName, depType, currentValue) tuples that must be
# present. The version is part of the expectation: a regression that keeps every
# name and loses every constraint has to fail this.
EXPECTED: list[tuple[str, str, str, str, str | None]] = [
    # inline python_requirement, in all its shapes
    ("pants", "inline/BUILD.pants", "click", "python_requirement", "==8.0.0"),
    ("pants", "inline/BUILD.pants", "requests", "python_requirement", "==2.28.0"),
    ("pants", "inline/BUILD.pants", "urllib3", "python_requirement", ">=1.26,<2"),
    ("pants", "inline/BUILD.pants", "types-protobuf", "python_requirement", None),
    ("pants", "inline/BUILD.pants", "packaging", "python_requirement", "==23.0"),
    # the same dist pinned once per resolve: two separate dependencies
    ("pants", "inline/BUILD.pants", "pytest", "python_requirement", "==7.0.0"),
    # a generator source, named by the default and by the `source` field
    ("pants", "default-source/requirements.txt", "charset-normalizer", "python_requirements", "==3.0.0"),
    ("pants", "default-source/requirements.txt", "idna", "python_requirements", ">=3.0,<4"),
    ("pants", "named-source/prod-requirements.txt", "certifi", "python_requirements", "==2023.7.22"),
    # fields other than name/requirements/source are ignored, but the source
    # itself is still extracted
    ("pants", "inline/ignored-requirements.txt", "attrs", "python_requirements", "==23.1.0"),
    # PEP 621, including a PEP 735 dependency group
    ("pants", "pep621/pyproject.toml", "typing-extensions", "project.dependencies", "==4.7.0"),
    ("pants", "pep621/pyproject.toml", "pytest-mock", "dependency-groups", "==3.10.0"),
    # Poetry, including a dependency group
    ("pants", "poetry/pyproject.toml", "tenacity", "dependencies", "^8.2.0"),
    ("pants", "poetry/pyproject.toml", "ruff", "dev", "^0.5.0"),
    # uv reads `[tool.uv] dev-dependencies`, and the file's own `[project]`
    ("pants", "uv/pyproject.toml", "httpx", "project.dependencies", ">=0.24.0,<0.28.0"),
    ("pants", "uv/pyproject.toml", "pytest-asyncio", "tool.uv.dev-dependencies", "==0.21.0"),
    # an unrelated `[tool.poetry-*]` table must not route the file to Poetry,
    # which would drop the uv dependencies
    ("pants", "poetry-prefixed-tool/pyproject.toml", "pyyaml", "project.dependencies", "==6.0"),
    (
        "pants",
        "poetry-prefixed-tool/pyproject.toml",
        "coverage",
        "tool.uv.dev-dependencies",
        "==7.3.0",
    ),
    # a build file named by `build_patterns`
    ("pants", "custom-build-file-name/pants_targets.py", "rich", "python_requirement", "==13.5.0"),
    # a VCS requirement keeps its git datasource
    ("pants", "vcs/BUILD.pants", "black", "python_requirement", "24.1.0"),
    # a Poetry project with a lock file is left to the poetry manager, which can
    # regenerate the lock file
    ("poetry", "poetry-locked/pyproject.toml", "jinja2", "dependencies", "^3.1.0"),
    # a requirements file with hashes is left to pip_requirements, which
    # refreshes them with `hashin`
    ("pip_requirements", "hashed/hashed-requirements.txt", "six", "", "==1.16.0"),
    # a generator target with no arguments at all: the documented form
    ("pants", "no-arguments/requirements.txt", "markupsafe", "python_requirements", "==2.0.0"),
    ("pants", "no-arguments-poetry/pyproject.toml", "filelock", "dependencies", "^3.12.0"),
    # a requirement written as adjacent string literals, which Python joins
    ("pants", "python-forms/BUILD.pants", "sqlparse", "python_requirement", ">=0.4.0,<0.5.0"),
    # a requirement in a tuple rather than a list
    ("pants", "python-forms/BUILD.pants", "wrapt", "python_requirement", "==1.14.0"),
    # a source that is not a literal: the target names no file this can read, so
    # the file it does name must be extracted by nobody, and the default file
    # must not be claimed instead (see FORBIDDEN)
    # a pip requirements file under a `.toml` name
    ("pants", "misnamed-toml/constraints.toml", "zipp", "python_requirements", "==3.8.0"),
    # two literals with an expression between them are two requirements
    (
        "pants",
        "expression-requirements/BUILD.pants",
        "decorator",
        "python_requirement",
        "==5.1.0",
    ),
    (
        "pants",
        "expression-requirements/BUILD.pants",
        "decorator",
        "python_requirement",
        "==5.1.1",
    ),
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
    # a target whose source is not a literal must not fall back to the default
    ("pants", "unresolved-source/requirements.txt"),
    ("pants", "unresolved-source/actual-requirements.txt"),
]


def main(report_path: str) -> int:
    report = json.loads(Path(report_path).read_text())
    repositories = report.get("repositories", {})

    found: set[tuple[str, str, str, str]] = set()
    raw_deps: list[dict] = []
    lock_claims: list[tuple[str, str, list[str]]] = []
    pytest_pins = 0

    for repo in repositories.values():
        for manager, package_files in (repo.get("packageFiles") or {}).items():
            for package_file in package_files:
                name = package_file["packageFile"]
                if manager == "pants" and "lockFiles" in package_file:
                    # Even an empty list is a claim this manager cannot honour,
                    # and it is what a regression would leave behind.
                    lock_claims.append((manager, name, package_file["lockFiles"]))
                for dep in package_file.get("deps") or []:
                    dep_name = dep.get("depName")
                    if dep_name is None:
                        continue  # interpreter constraint, not a requirement
                    found.add(
                        (
                            manager,
                            name,
                            dep_name,
                            dep.get("depType") or "",
                            dep.get("currentValue"),
                        )
                    )
                    raw_deps.append({**dep, "packageFile": name, "manager": manager})
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
        if any(m == manager and f == package_file for m, f, _, _, _ in found):
            failures.append(f"should have been superseded: ({manager}, {package_file})")

    # A requirement split across adjacent literals has to come back joined,
    # with its version: without the version there is nothing to update.
    joined = [
        d
        for d in raw_deps
        if d.get("packageFile") == "python-forms/BUILD.pants"
        and d.get("depName") == "sqlparse"
    ]
    if not joined or joined[0].get("currentValue") != ">=0.4.0,<0.5.0":
        failures.append(
            f"sqlparse should be joined to >=0.4.0,<0.5.0, got {joined}"
        )

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
