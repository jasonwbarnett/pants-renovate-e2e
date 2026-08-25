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
    # the neighbour of an abandoned element is still a requirement
    (
        "pants",
        "expression-requirements/BUILD.pants",
        "chardet",
        "python_requirement",
        "==5.2.0",
    ),
    # a specifier split across two literals: reported, but not updatable
    (
        "pants",
        "split-specifier/BUILD.pants",
        "sortedcontainers",
        "python_requirement",
        ">=1.0,<2.0",
    ),
    ("pants", "split-specifier/BUILD.pants", "cachetools", "python_requirement", ">=1.0,<2.0"),
    # a source whose name starts with BUILD is still a source
    (
        "pants",
        "build-prefixed-source/BUILD_requirements.txt",
        "wcwidth",
        "python_requirements",
        "==0.2.6",
    ),
    # a hashed file `pip_requirements` does not claim by name is reported here,
    # skipped, rather than left to nobody
    ("pants", "hashed-unmatched/constraints.txt", "six", "python_requirements", "==1.16.0"),
    # a build file whose name looks like a requirements file
    ("pants", "custom-build-ext/app.build.toml", "rich", "python_requirement", "==13.4.0"),
    # ...and a source whose name a configured pattern also covers, which is
    # claimed rather than refused because the target says what it is
    (
        "pants",
        "pattern-covered-source/constraints.build.toml",
        "sniffio",
        "python_requirements",
        "==1.3.0",
    ),
]

# (packageFile, depName) -> fields that are load-bearing for that fixture,
# checked where they say something rather than on every row.
DEP_FIELDS: dict[tuple[str, str], dict[str, object]] = {
    # a VCS requirement resolves against git tags, under its URL
    ("vcs/BUILD.pants", "black"): {
        "datasource": "git-tags",
        "packageName": "https://github.com/psf/black",
    },
    # an ordinary requirement resolves on PyPI, under the name as written
    ("inline/BUILD.pants", "types-protobuf"): {
        "datasource": "pypi",
        "packageName": "types-protobuf",
    },
    # a hashed file this manager cannot rewrite is reported, and skipped
    ("hashed-unmatched/constraints.txt", "six"): {"skipReason": "unsupported"},
    # a split specifier has no text to anchor a replacement on
    ("split-specifier/BUILD.pants", "sortedcontainers"): {
        "skipReason": "unsupported",
        "replaceString": None,
    },
    # the target that writes the same range whole is updatable
    ("split-specifier/BUILD.pants", "cachetools"): {
        "skipReason": None,
        "replaceString": "cachetools>=1.0,<2.0",
    },
    # How the file was read is recorded on the dependency, because the option
    # that would answer it later is stripped before the update is written.
    ("custom-build-ext/app.build.toml", "rich"): {
        "managerData": {"pantsReadAs": "buildFile"},
    },
    ("pattern-covered-source/constraints.build.toml", "sniffio"): {
        "managerData": {"pantsReadAs": "source"},
    },
    ("default-source/requirements.txt", "idna"): {
        "managerData": {"pantsReadAs": "source"},
    },
}

# (manager, packageFile, depName) triples that must NOT appear. A name that is
# only part of an expression is worse than a name that is missing: it produces
# an edit into code rather than into a requirement.
FORBIDDEN_DEPS: list[tuple[str, str, str]] = [
    ("pants", "expression-requirements/BUILD.pants", "flask"),
    ("pants", "expression-requirements/BUILD.pants", "alembic"),
    ("pants", "expression-requirements/BUILD.pants", "foo"),
    ("pants", "expression-requirements/BUILD.pants", "httpx"),
    ("pants", "expression-requirements/BUILD.pants", "starlette"),
    ("pants", "expression-requirements/BUILD.pants", "django"),
    ("pants", "expression-requirements/BUILD.pants", "pyarrow"),
    # neither arm of a conditional: Pants only ever holds one of them
    ("pants", "expression-requirements/BUILD.pants", "decorator"),
    ("pants", "expression-requirements/BUILD.pants", "orjson"),
    # a fenced example in a documentation file is not a target, and the file it
    # names is not a source
    ("pants", "docs/BUILD.md", "flask"),
    ("pants", "docs/requirements.txt", "doc-only-dep"),
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
    # ...whichever way the expression is written
    ("pants", "unresolved-source/first-requirements.txt"),
    ("pants", "unresolved-source/second-requirements.txt"),
    ("pants", "unresolved-source/prefix-.txt"),
    # a hashed file under a name `pip_requirements` does not claim belongs to
    # nobody else, so that manager must not report it either
    ("pip_requirements", "hashed-unmatched/constraints.txt"),
    # a source Pants itself would read as a build file: a contradiction in the
    # repository, so neither file is claimed
    ("pants", "source-named-build/BUILD.txt"),
    ("pants", "source-named-build/BUILD.pants"),
]


def main(report_path: str) -> int:
    report = json.loads(Path(report_path).read_text())
    repositories = report.get("repositories", {})

    # A run that cannot load the manager at all still exits 0 and writes no
    # report, so without this guard these assertions pass against the report an
    # earlier run left behind. Refuse a report that describes nothing rather
    # than trusting it.
    total_deps = sum(
        len(package_file.get("deps") or [])
        for repo in repositories.values()
        for package_files in (repo.get("packageFiles") or {}).values()
        for package_file in package_files
    )
    if not repositories or not total_deps:
        print(
            f"the report at {report_path} describes {len(repositories)} repositories "
            f"and {total_deps} dependencies -- did the run actually happen?"
        )
        return 1

    found: set[tuple[str, str, str, str]] = set()
    raw_deps: list[dict] = []
    lock_claims: list[tuple[str, str, list[str]]] = []
    package_file_entries: list[dict] = []
    pytest_pins = 0

    for repo in repositories.values():
        for manager, package_files in (repo.get("packageFiles") or {}).items():
            for package_file in package_files:
                name = package_file["packageFile"]
                package_file_entries.append({**package_file, "manager": manager})
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

    for manager, package_file, dep_name in FORBIDDEN_DEPS:
        if any(
            m == manager and f == package_file and d == dep_name
            for m, f, d, _, _ in found
        ):
            failures.append(
                f"expression read as a requirement: ({manager}, {package_file}, {dep_name})"
            )

    for (package_file, dep_name), fields in DEP_FIELDS.items():
        matching = [
            d
            for d in raw_deps
            if d["manager"] == "pants"
            and d["packageFile"] == package_file
            and d.get("depName") == dep_name
        ]
        if not matching:
            failures.append(f"missing dependency for field check: {package_file} {dep_name}")
            continue
        for field, expected in fields.items():
            actual = matching[0].get(field)
            if actual != expected:
                failures.append(
                    f"{package_file} {dep_name}: {field} is {actual!r}, expected {expected!r}"
                )

    # Exactly the dependencies this repository declares to be unreplaceable, and
    # no others. `assert_updates.mjs` skips these, so its floor cannot see them.
    unsupported = sorted(
        (d["packageFile"], d.get("depName"))
        for d in raw_deps
        if d["manager"] == "pants" and d.get("skipReason") == "unsupported"
    )
    # `poetry-locked/pyproject.toml` is not here: the poetry manager keeps that
    # file outright, so this manager reports no entry for it to skip.
    expected_unsupported = [
        ("hashed-unmatched/constraints.txt", "six"),
        ("split-specifier/BUILD.pants", "sortedcontainers"),
    ]
    if unsupported != expected_unsupported:
        failures.append(
            f"unreplaceable dependencies are {unsupported}, expected {expected_unsupported}"
        )

    # An index a source names is metadata Renovate needs to resolve the
    # requirements in it, and it has to survive the rebuild that drops the lock
    # files.
    indexed = [
        f
        for f in package_file_entries
        if f["manager"] == "pants"
        and f["packageFile"] == "default-source/requirements.txt"
    ]
    if not indexed or indexed[0].get("registryUrls") != ["https://pypi.org/simple"]:
        failures.append(
            f"default-source/requirements.txt should keep its index, got {indexed}"
        )

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

    print(f"checked {len(EXPECTED) + len(FORBIDDEN) + len(FORBIDDEN_DEPS) + len(DEP_FIELDS)} expectations against {len(found)} extracted dependencies")
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
