# pants-renovate-e2e

An end-to-end test bed for the [Pants](https://www.pantsbuild.org) manager proposed in
[renovatebot/renovate#45321](https://github.com/renovatebot/renovate/pull/45321).

Every directory here exists to exercise one code path of that manager.
The [`renovate-e2e`](../../actions/workflows/renovate-e2e.yml) workflow runs Renovate from the pull request branch against this repository on every push, and asserts one expectation per path, so a regression fails a check instead of hiding in a log.
The same workflow can be dispatched with `open_prs` to run Renovate for real, in which case the pull requests it opens show the edits it makes.

The dependencies here are deliberately out of date and pinned, so that every path produces a pull request whose diff shows the edit being made.

Two runs prove different things:

- every push runs `renovate --platform=local`, which needs no credentials and writes nothing, and then asserts one expectation per code path
- a dispatched run with `open_prs` runs Renovate against this repository for real, so the [open pull requests](../../pulls) are the file edits it makes

## What each path proves

| Path                                       | Pants target                                | What it covers                                                                    |
| ------------------------------------------ | ------------------------------------------- | --------------------------------------------------------------------------------- |
| `inline/BUILD.pants`                       | `python_requirement`                        | Requirements written in the build file, with extras, with no version, and repeated |
| `inline/BUILD.pants`                       | `python_requirement` twice                  | The same dist pinned once per resolve, which has to update each target separately  |
| `inline/BUILD.pants`                       | `resolve=parametrize(...)`                  | A requirement that belongs to two resolves at once                                 |
| `inline/BUILD.pants`                       | `module_mapping`, `overrides`               | Fields that must never be read as requirements                                     |
| `default-source/`                          | `python_requirements`                       | The default `requirements.txt` source                                              |
| `named-source/`                            | `python_requirements(source=...)`           | A source named by the target                                                       |
| `pep621/`                                  | `python_requirements(source=pyproject.toml)` | A PEP 621 source, including a PEP 735 dependency group                             |
| `poetry/`                                  | `poetry_requirements`                       | A Poetry source, including a Poetry dependency group                               |
| `no-arguments/`, `no-arguments-poetry/`     | `python_requirements()`, `poetry_requirements()` | A generator target with no arguments at all, the documented form, which relies entirely on the field defaults |
| `python-forms/`                            | `python_requirement`                        | A requirement written as adjacent string literals, which Python joins, and one written in a tuple |
| `hashed/`                                  | `python_requirements` over a `--hash=` file  | A requirements file whose hashes must be refreshed when a pin changes, so it is left to `pip_requirements` |
| `poetry-locked/`                           | `poetry_requirements` plus `poetry.lock`     | A source whose lock file this manager cannot regenerate, so the `poetry` manager keeps it. This one is checked by the assertions rather than by a pull request, because regenerating a Poetry lock file needs Poetry installed |
| `uv/`                                      | `uv_requirements`                           | `[tool.uv] dev-dependencies`, and the `[project]` dependencies of the same file    |
| `poetry-prefixed-tool/`                    | `python_requirements(source=pyproject.toml)` | A PEP 621 file carrying `[tool.poetry-dynamic-versioning]`, which is not Poetry     |
| `custom-build-file-name/pants_targets.py`  | `python_requirement`                        | A build file named by `build_patterns` rather than `BUILD`                         |
| `vcs/BUILD.pants`                          | `python_requirement`                        | A `git+https` requirement, which keeps its git datasource                          |

## Running it yourself

```bash
git clone https://github.com/altana-ai/renovate --branch feat/pants-manager .renovate-src
(cd .renovate-src && pnpm install --frozen-lockfile)

RENOVATE_PLATFORM=local \
  RENOVATE_REPORT_TYPE=file \
  RENOVATE_REPORT_PATH="$PWD/report.json" \
  node .renovate-src/lib/renovate.ts --dry-run=extract

python3 scripts/assert_extraction.py report.json
```

`--platform=local` writes nothing and needs no credentials.

To run the workflow against one specific commit of the manager rather than
whatever the branch points at:

```bash
gh api -X POST repos/jasonwbarnett/pants-renovate-e2e/dispatches \
  -f event_type=manager-changed \
  -f "client_payload[sha]=$(git rev-parse HEAD)"
```

`git rev-parse HEAD` rather than a shortened SHA: the checkout is shallow, and a
shallow fetch of an abbreviated SHA fails with nothing more useful than `git
failed with exit code 1`.

## What the last run showed

Every path above produced a pull request, including the two that the review of
the pull request asked about:

- one dist pinned in two targets, one per resolve, updates **both** targets in a
  single pull request, because `doAutoReplace` walks the later occurrences
- a `pyproject.toml` carrying `[tool.poetry-dynamic-versioning]` is read as
  PEP 621, so its `[tool.uv]` dependencies are updated instead of being lost

A build file named by `build_patterns` rather than `BUILD` is updated as well,
which is what the earlier name-based check got wrong.

## What a green run does not prove

The assertions here are checked by breaking the manager one change at a time and
requiring that at least one of the two scripts goes red. 42 such changes are
tested; 39 are caught. The three that are not, and why:

- **Reading the pattern list as a whole instead of one pattern at a time.** Only
  observable when the list holds a negated pattern, and a negation makes
  `getMatchingFiles` hand this manager every file that is not excluded, which
  would make every other expectation here meaningless. Covered by a unit test.
- **Loosening the build-file-name test where `isBuildFile` falls back to it.**
  That branch is only reached by a caller that passes no patterns at all, and
  every route through this repository passes them. Unit tests cover it. The
  production-reachable use of the same test — refusing a source that Pants
  itself would read as a build file — is a separate mutation, and it is caught.
- **Widening the default `managerFilePatterns`.** This one is not a gap: a wider
  default only hands the manager more files, and a file that is not a build file
  parses to no targets and produces nothing. There is no defect to catch.

Both are stated here rather than left implicit, because the point of this
repository is that a green run means something specific.

A green run also used to be possible with no run at all: `renovate
--dry-run=extract` exits 0 when the manager cannot be loaded, and writes no
report, so the assertions were checked against whatever report an earlier run
had left behind. The workflow now deletes the report before the run and requires
a non-empty one after it, and `assert_extraction.py` refuses a report that
describes no dependencies rather than trusting it.

A green run also used to be possible while every file was handed a config about
itself. A branch config describes its first upgrade, so a branch spanning a
build file and a source hands one reading to both, and `assert_updates.mjs` now
re-extracts each of the pair with the other's config and requires the same
answer.

And a green run used to be possible against an upgrade Renovate does not build.
`assert_updates.mjs` assembled the upgrade by hand, including
`managerFilePatterns` — which Renovate strips before the branch stage, because
it is a repository-stage option. So a build file under a configured name passed
here and failed in production on every run. The script now spreads the whole
dependency the way `flattenUpdates` does and passes the result through
`filterConfig(upgrade, 'branch')`, so it can only test the upgrade shape that
actually reaches auto-replace.
