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

## What the last run showed

Every path above produced a pull request, including the two that the review of
the pull request asked about:

- one dist pinned in two targets, one per resolve, updates **both** targets in a
  single pull request, because `doAutoReplace` walks the later occurrences
- a `pyproject.toml` carrying `[tool.poetry-dynamic-versioning]` is read as
  PEP 621, so its `[tool.uv]` dependencies are updated instead of being lost

A build file named by `build_patterns` rather than `BUILD` is updated as well,
which is what the earlier name-based check got wrong.
