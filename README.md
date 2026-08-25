# pants-renovate-e2e

An end-to-end test bed for the [Pants](https://www.pantsbuild.org) manager proposed in
[renovatebot/renovate#45321](https://github.com/renovatebot/renovate/pull/45321).

Every directory here exists to exercise one code path of that manager.
The [`renovate-e2e`](../../actions/workflows/renovate-e2e.yml) workflow runs Renovate from the pull request branch against this repository on every push, and asserts one expectation per path, so a regression fails a check instead of hiding in a log.
The same workflow can be dispatched with `open_prs` to run Renovate for real, in which case the pull requests it opens show the edits it makes.

Roughly half of these paths exist to prove an update lands: their dependencies are deliberately out of date and pinned, so a dispatched run opens a pull request whose diff shows the edit.
The other half exist to prove nothing is proposed — prose refused, an expression not read, a source whose name cannot be resolved, a lock file left to the manager that owns it.
Those cannot produce a pull request, and that is what they are for, so the assertions are what check them.

Two runs prove different things:

- every push runs `renovate --platform=local`, which needs no credentials and writes nothing, and then asserts one expectation per code path
- a dispatched run with `open_prs` runs Renovate against this repository for real, so the [open pull requests](../../pulls) are the file edits it makes

## What each path proves

| Path                                      | Pants target                                         | What it covers                                                                                                                                                                                                                 |
| ----------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `inline/BUILD.pants`                      | `python_requirement`                                 | Requirements written in the build file, with extras, with no version, and repeated                                                                                                                                             |
| `inline/BUILD.pants`                      | `python_requirement` twice                           | The same dist pinned once per resolve, which has to update each target separately                                                                                                                                              |
| `inline/BUILD.pants`                      | `resolve=parametrize(...)`                           | A requirement that belongs to two resolves at once                                                                                                                                                                             |
| `inline/BUILD.pants`                      | `module_mapping`, `overrides`                        | Fields that must never be read as requirements                                                                                                                                                                                 |
| `default-source/`                         | `python_requirements`                                | The default `requirements.txt` source                                                                                                                                                                                          |
| `named-source/`                           | `python_requirements(source=...)`                    | A source named by the target                                                                                                                                                                                                   |
| `pep621/`                                 | `python_requirements(source=pyproject.toml)`         | A PEP 621 source, including a PEP 735 dependency group                                                                                                                                                                         |
| `poetry/`                                 | `poetry_requirements`                                | A Poetry source, including a Poetry dependency group                                                                                                                                                                           |
| `no-arguments/`, `no-arguments-poetry/`   | `python_requirements()`, `poetry_requirements()`     | A generator target with no arguments at all, the documented form, which relies entirely on the field defaults                                                                                                                  |
| `python-forms/`                           | `python_requirement`                                 | A requirement written as adjacent string literals, which Python joins, and one written in a tuple                                                                                                                              |
| `hashed/`                                 | `python_requirements` over a `--hash=` file          | A requirements file whose hashes must be refreshed when a pin changes, so it is left to `pip_requirements`                                                                                                                     |
| `poetry-locked/`                          | `poetry_requirements` plus `poetry.lock`             | A source whose lock file this manager cannot regenerate, so the `poetry` manager keeps it. This one is checked by the assertions rather than by a pull request, because regenerating a Poetry lock file needs Poetry installed |
| `uv/`                                     | `uv_requirements`                                    | `[tool.uv] dev-dependencies`, and the `[project]` dependencies of the same file                                                                                                                                                |
| `poetry-prefixed-tool/`                   | `python_requirements(source=pyproject.toml)`         | A PEP 621 file carrying `[tool.poetry-dynamic-versioning]`, which is not Poetry                                                                                                                                                |
| `custom-build-file-name/pants_targets.py` | `python_requirement`                                 | A build file named by `build_patterns` rather than `BUILD`                                                                                                                                                                     |
| `vcs/BUILD.pants`                         | `python_requirement`                                 | A `git+https` requirement, which keeps its git datasource                                                                                                                                                                      |
| `bare-build/BUILD`                        | `python_requirement`                                 | `BUILD` with no extension, the first entry in Pants' own default patterns                                                                                                                                                      |
| `custom-build-ext/app.build.toml`         | `python_requirement`                                 | A build file whose configured name ends in a source format's extension, read correctly because its content decides                                                                                                             |
| `build-ext-txt/app.build.txt`             | `python_requirement`                                 | The other side of that trade: a build file under an extension only a source carries, which only the recorded reading can route                                                                                                 |
| `build-prefixed-source/`                  | `python_requirements(source=BUILD_requirements.txt)` | A source whose name starts with `BUILD` but is not a build-file name                                                                                                                                                           |
| `source-named-build/`                     | `python_requirements(source=BUILD.txt)`              | A target naming a source Pants itself reads as a build file: a contradiction, so the source is refused and the build file keeps its own pins                                                                                   |
| `pattern-covered-source/`                 | `python_requirements(source=*.build.toml)`           | A source a configured build-file pattern also covers, claimed anyway because the target says what it is                                                                                                                        |
| `mixed-source/pins.txt`                   | `python_requirements(source=pins.txt)`               | A conventionally named source holding a line that parses as a target, read by its extension rather than its content                                                                                                            |
| `record-decides/constraints`              | `python_requirements(source=constraints)`            | The same with no extension at all, which nothing but the recorded reading can route — the one file in the derived record-dependent set                                                                                         |
| `misnamed-toml/`                          | `python_requirements(source=constraints.toml)`       | A pip requirements file under a `.toml` name                                                                                                                                                                                   |
| `upper-ext-source/`                       | `poetry_requirements(source=pyproject.TOML)`         | An extension differing from the check only in case                                                                                                                                                                             |
| `docs/`, `prose-source/`                  | prose named like a build file, and named as a source | `BUILD.md`, `BUILD.MD` and `BUILD.adoc`, plus a target naming `notes.md`: prose is refused whatever a pattern says                                                                                                             |
| `expression-requirements/`                | `python_requirement`                                 | Every way of building or choosing a requirement with an expression — concatenation, interpolation, a subscript, a method call, a conditional, a call argument, and an expression around the whole field                        |
| `split-specifier/`                        | `python_requirement`                                 | A version specifier split across two literals, which nothing in the file can replace, plus a decoy writing the same range whole                                                                                                |
| `unresolved-source/`                      | `python_requirements(source=<expression>)`           | A source given as a variable, a pair, a concatenation or an interpolation: none falls back to the default                                                                                                                      |
| `hashed-unmatched/`                       | `python_requirements(source=constraints.txt)`        | A hashed file under a name `pip_requirements` does not claim by default, reported as skipped — and this repository widens that manager's patterns to cover it, so both report it and it matters which keeps it                 |
| `locked-odd-name/`                        | `poetry_requirements(source=poetry-project.toml)`    | A locked source under a name `poetry` does not match, so nothing supersedes and the entry has to say it claims nothing                                                                                                         |
| `poetry-path-override/`                   | `poetry_requirements`                                | `[project]` constraint with a `[tool.poetry]` path override, where the delegate's own skip must not be read as this manager being unable to maintain the file. The counterexample the shared-code change is designed around    |

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

`git rev-parse HEAD` rather than a shortened SHA: the checkout is shallow, so a
short SHA cannot be fetched. The workflow checks the ref before the checkout and
says so by name, which it did not do the first two times this caught me.

## What the last run showed

Every path above that can produce a pull request did, including the two that the
review of the pull request asked about:

- one dist pinned in two targets, one per resolve, updates **both** targets in a
  single pull request, because `doAutoReplace` walks the later occurrences
- a `pyproject.toml` carrying `[tool.poetry-dynamic-versioning]` is read as
  PEP 621, so its `[tool.uv]` dependencies are updated instead of being lost

A build file named by `build_patterns` rather than `BUILD` is updated as well,
which is what the earlier name-based check got wrong.

## What a green run does not prove

The assertions here are checked by breaking the manager one change at a time and
requiring that at least one of the two scripts goes red. 47 such changes are
tested; 46 are caught. The one that is not:

- **Widening the default `managerFilePatterns`.** This is not a gap: a wider
  default only hands the manager more files, and a file that is not a build file
  parses to no targets and produces nothing. There is no defect to catch.

Four earlier entries have left this list, each because a route was found to the
code they broke rather than because the code was removed — the pattern-list
reading, the build-file-name fallback and the pattern branch of the routing. The
last of those is gone from the manager entirely: it could not be reached and it
was less correct than the branch after it.

A green run also used to be possible with no run at all: `renovate
--dry-run=extract` exits 0 when the manager cannot be loaded, and writes no
report, so the assertions were checked against whatever report an earlier run
had left behind. The workflow now deletes the report before the run and requires
a non-empty one after it, and `assert_extraction.py` refuses a report that
describes no dependencies rather than trusting it.

A green run used to be possible while every file was handed a config about
itself. A branch config describes its first upgrade, so a branch spanning a
build file and a source hands one reading to both, and `assert_updates.mjs` now
re-extracts each of the pair with the other's config and requires the same
answer.

A green run used to be possible against an upgrade Renovate does not build.
`assert_updates.mjs` assembled the upgrade by hand, including
`managerFilePatterns` — which Renovate strips before the branch stage, because
it is a repository-stage option. The script now spreads the whole dependency the
way `flattenUpdates` does and passes the result through
`filterConfig(upgrade, 'branch')`.

And a green run used to say nothing about a warm extract cache. The fingerprint
that invalidates a cached extraction covers a manager's tests, not its
implementation, so an implementation-only change can pair new code with
dependencies extracted by the old code — which have no recorded reading. Every
update here is therefore applied twice, once with that record and once without,
and both have to land. The set of files that cannot survive it is
**derived and asserted** rather than listed: a file is record-dependent when
reading it without the record disagrees with how extraction read it, which is a
computation, and a hand-written list can only be wrong in the direction that
hides a gap. Today that set has two members, one from each direction of
the same trade: a source whose name the extension allowlist does not cover and
whose text reads like a build file, and a build file whose configured name
carries an extension the allowlist does. Both need a name nobody writes by
accident, and the derivation reports the membership so nobody has to remember
it.

The degraded runs have a floor of their own, for the same reason the recorded
ones do: without it, widening that set to everything would leave this script
green with no degraded coverage at all.

The two mutations that break `supersedes.ts` — ignoring `cannotUpdate`, and
inferring it from the dependencies the way an earlier version did — are only
meaningful because this repository configures a real collision.
`pip_requirements.managerFilePatterns` is widened to cover
`hashed-unmatched/constraints.txt`, so two managers report that file and it
matters which one keeps it; and `poetry-path-override/pyproject.toml` is the
layout where a delegate's own skip must not be read as "this manager cannot
maintain the file". Without those two, both mutations pass: the assertions would
prove the field is set and nothing would prove it is read.

Running those mutations at all needed the sweep hardened. Its pristine snapshot
now comes from `git show` rather than from the working copy, every path any
mutation can write is listed explicitly rather than covered by directory, and
each reset is verified with `cmp` before the next case runs. Without all three, a
mutation to a shared file leaks into the following case and the sweep becomes
order-dependent — which is worse than wrong, because it looks like a result.

The sweep that produces those numbers had three ways left to report success it
had not earned, all of them in the checking rather than the mutating — which is
the harder half, because a check that cannot fail looks exactly like a check
that passes. Its reset compared the copy against the snapshot it had just been
made from, so it verified that `cp` ran and nothing more. Its copy was built from
the working tree and then had six files overwritten from git, so a result was
about a mixture of two revisions. And a mutation that produced unparseable code
made the assertions die on a missing report, which exits nonzero — and nonzero is
the definition of CAUGHT, so total breakage read as total success.

All three are closed the same way: the copy comes entirely from `git archive` at
an explicit revision, a dirty tree refuses to run, each reset is compared against
`git show`, the report must exist after every run, and case zero mutates nothing
and must come back green. That last one is what found the first fault after the
rebuild — a set of generated files `git archive` does not carry — within a minute
of being added.

Two more preconditions the sweep states rather than assumes. The set of files it
restores between cases is asked of the mutation script rather than declared, so a
new mutation target cannot be left unrestored — the same argument as for the
record-dependent set, and the same direction of failure. And it refuses to run
against a dirty test bed: `assert_updates.mjs` restores what it writes in a
`finally`, which covers a throw but not a kill or a timeout, and a bed left
mutated makes the next run measure that instead. That produces findings with no
defect behind them, which has happened to both of the harnesses used on this
work.

The sweep also names the test bed's revision, not only the manager's. A result
here is a statement about a pair of commits, and a clean checkout at the wrong
one passes any dirty check, so the pair is printed and an expected bed revision
can be required.

The sixth instance of the same pattern was in the code added to close the fifth.
The hashed tier pinned a gitignored file's hash at setup and compared it at each
reset — but a missing file gives an empty hash on both sides, and empty equals
empty, so a path with no file in the copy passed as reset. The general form is
worth keeping alongside the first: **a comparison is only a check if both sides
can be obtained independently. If the same failure produces both, it proves
nothing.**

The bed-revision gate resolves what it is given through the bed rather than
comparing it as a string, so the short SHA from `git log --oneline` — the only
form anyone has to hand — is accepted, along with a tag or a branch. A gate that
rejects the value you would naturally give it gets deleted rather than
lengthened. Resolving it there also separates two failures that used to look
alike: a revision that is not in that repository at all now says so, instead of
reading as the wrong revision.
