// Applies an update to every dependency this repository declares, using the
// same code path Renovate uses to write a branch, and checks that the right
// text moved. Extraction alone would not catch an update that silently fails.
//
// Usage: node scripts/assert_updates.mjs <path-to-renovate-checkout> <report.json>
//
// The report is the one the extraction step writes, and it is required: it is
// what this script compares its own population against, rather than rebuilding
// the config resolution that produced it.

import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const renovateSrc = resolve(process.argv[2] ?? ".renovate-src");
const reportPath = process.argv[3];
const repoDir = process.cwd();

if (!reportPath) {
  throw new Error(
    "usage: assert_updates.mjs <path-to-renovate-checkout> <report.json>",
  );
}

const { GlobalConfig } = await import(`${renovateSrc}/lib/config/global.ts`);
const { extractAllPackageFiles, extractPackageFile } = await import(
  `${renovateSrc}/lib/modules/manager/pants/index.ts`
);
const { doAutoReplace } = await import(
  `${renovateSrc}/lib/workers/repository/update/branch/auto-replace.ts`
);
// Renovate filters every update down to the branch stage before it reaches
// auto-replace, which drops repository-stage options such as
// `managerFilePatterns`. Building the upgrade by hand and skipping that filter
// is how this script passed while the same update failed in production.
const { filterConfig } = await import(`${renovateSrc}/lib/config/index.ts`);

GlobalConfig.set({ localDir: repoDir });

// The manager config this repository sets, merged with the manager's own
// default the way Renovate merges it, and passed to both entry points. Without
// the repository's half, the routing cannot know that a build file named
// `app.build.toml` is one; without the default half, it cannot know that
// `BUILD.pants` is.
const { defaultConfig } = await import(
  `${renovateSrc}/lib/modules/manager/pants/index.ts`
);
const repoConfig = JSON.parse(
  readFileSync(resolve(repoDir, "renovate.json"), "utf8"),
).pants;
const managerConfig = {
  ...repoConfig,
  managerFilePatterns: [
    ...defaultConfig.managerFilePatterns,
    ...repoConfig.managerFilePatterns,
  ],
};

// Every dependency this repository declares and Renovate can update. A
// regression that stops extracting some of them would otherwise leave this
// script testing less and still exiting zero.
// Files the recorded reading is the only thing that can route: their name says
// nothing (no extension at all) and their content says the wrong thing. Asserted
// rather than used as a skip list, so a file joining the set fails here instead
// of quietly losing its degraded coverage.
// Two, one from each direction of the source-extension trade: a source whose
// name the allowlist does not cover and whose text reads like a build file, and
// a build file whose configured name carries an extension the allowlist does.
const EXPECTED_RECORD_DEPENDENT = [
  "build-ext-txt/app.build.txt",
  "record-decides/constraints",
];

const EXPECTED_UPDATES = 37;

// One per record-dependent file fewer, by construction: those cannot be updated
// without the record. Derived rather than restated, so the two numbers cannot
// drift apart the way they already did once.
const EXPECTED_DEGRADED_UPDATES =
  EXPECTED_UPDATES - EXPECTED_RECORD_DEPENDENT.length;

// The files Renovate would hand this manager, asked of Renovate's own matcher
// over the config this script already builds. A glob list here can miss a name
// the patterns cover -- and did, twice: `*.build.txt`, and then a bare `BUILD`,
// which is the first entry in Pants' own default patterns. Everything below is
// downstream of this, so a missed file is invisible to the record-dependent
// derivation, both floors and the double-apply, and the derivation then returns
// the expected answer for the wrong population.
const { getMatchingFiles } = await import(
  `${renovateSrc}/lib/workers/repository/extract/file-match.ts`
);
// The path options come from the repository config where it sets them and from
// Renovate's own defaults where it does not, which is the order Renovate
// resolves them in. This is still a reconstruction, though, so it is not what
// the correctness of the population rests on -- the comparison against the
// run's report below is. Two earlier versions of this block diverged from the
// run: hardcoding `[]` made it wider (a false red), and overriding the
// repository's value with the option default made it narrower (a false green).
const { getOptions } = await import(
  `${renovateSrc}/lib/config/options/index.ts`
);
const optionDefault = (name) =>
  getOptions().find((option) => option.name === name).default;

const buildFiles = getMatchingFiles(
  {
    includePaths: optionDefault("includePaths"),
    ignorePaths: optionDefault("ignorePaths"),
    ...managerConfig,
    manager: "pants",
  },
  execFileSync("git", ["ls-files"], { cwd: repoDir, encoding: "utf8" })
    .split("\n")
    .filter(Boolean),
);
if (!buildFiles.length) {
  throw new Error("no build files matched: this script would test nothing");
}

const packageFiles = await extractAllPackageFiles(managerConfig, buildFiles);

const failures = [];
let checked = 0;
let degradedChecked = 0;

// Every file the real run claimed has to be one this script knows about, either
// as a build file its population matched or as a generator source discovered
// from one. Compared against the run's own report rather than recomputed, so no
// config option, preset, or future change to how Renovate resolves them can
// take a file out of this script's view without failing here.
//
// Only this direction is asserted. A file this script tests and the run ignores
// costs someone an hour; a file the run updates and this script never tests
// costs a regression.
//
// And only this much of the claim surface. `claimed` is what survives
// supersedes, so a file this manager wrongly claims and another manager takes
// back is invisible here -- that direction is `assert_extraction.py`'s
// `FORBIDDEN` list. The two scripts divide the space and neither bounds it
// alone.
const report = JSON.parse(readFileSync(resolve(reportPath), "utf8"));
const claimed = Object.values(report.repositories ?? {}).flatMap((repo) =>
  (repo.packageFiles?.pants ?? []).map((f) => f.packageFile),
);
// A floor, not just non-emptiness. A reference listing one of twenty-seven files
// passes an emptiness check and then has a twenty-seventh of its discriminating
// power -- the same fault as empty-compared-with-empty, one notch above zero.
// Reachable through a stale report from a bed with fewer fixtures, or a partial
// run: we have already seen extraction exit 0 having written no package files at
// all, and a partial population is no less likely than an empty one.
//
// Deliberately not compared for equality with this script's own count, though
// the two are close. `claimed` is the population *after* supersedes, so
// `poetry-locked/pyproject.toml` sits under `poetry` and is absent from it,
// while this script's own extraction has no supersedes step and includes it.
// Two sets of nearly the same size with different members; equality would fail
// the first time supersedes moved one more file.
const EXPECTED_CLAIMED = 27;
if (claimed.length < EXPECTED_CLAIMED) {
  failures.push(
    `the report at ${reportPath} lists ${claimed.length} pants package files, expected at least ${EXPECTED_CLAIMED}: a truncated reference cannot fail`,
  );
}
const known = new Set([
  ...buildFiles,
  ...packageFiles.map((f) => f.packageFile),
]);
const unseen = claimed.filter((f) => !known.has(f));
if (unseen.length) {
  failures.push(
    `the run claimed files this script never saw: ${JSON.stringify(unseen)}`,
  );
}

// A file is record-dependent when reading it without the record disagrees with
// how extraction read it. Computed rather than declared: the condition is
// mechanical, and a list can only be wrong in the direction that hides a gap.
const recordDependent = [];
for (const pf of packageFiles) {
  const content = readFileSync(resolve(repoDir, pf.packageFile), "utf8");
  const degraded = await extractPackageFile(content, pf.packageFile, {
    ...managerConfig,
    packageFile: pf.packageFile,
  });
  // Name and version, not name alone: a source holding a target line that pins
  // the same package at another version reads as the same set of names, and the
  // difference only shows up in what would be written.
  const recorded = pf.deps.map((d) => `${d.depName}@${d.currentValue}`).sort();
  const guessed = (degraded?.deps ?? [])
    .map((d) => `${d.depName}@${d.currentValue}`)
    .sort();
  if (JSON.stringify(recorded) !== JSON.stringify(guessed)) {
    recordDependent.push(pf.packageFile);
  }
}
if (
  JSON.stringify(recordDependent.sort()) !==
  JSON.stringify(EXPECTED_RECORD_DEPENDENT)
) {
  failures.push(
    `record-dependent files are ${JSON.stringify(recordDependent)}, expected ${JSON.stringify(EXPECTED_RECORD_DEPENDENT)}`,
  );
}

// Prose that the patterns match has to be refused by the single-file entry
// point as well, not only skipped by the walk. That entry point is the
// auto-replace confirmation, and it is the only place a difference between the
// two shows up: a file the walk skips and this one reads is a file Renovate
// would offer to edit and then fail on.
// Read out of the manager rather than listed, so an extension added there is
// covered here without anyone remembering to. A list of names would prove the
// check ran while covering a fraction of what it claims -- which it did, three
// of eight.
const proseExtensions = [
  ...readFileSync(
    resolve(renovateSrc, "lib/modules/manager/pants/extract.ts"),
    "utf8",
  )
    .match(/const proseExtensions = new Set\(\[([^\]]*)\]\)/)[1]
    .matchAll(/'([^']+)'/g),
].map((m) => m[1]);

if (proseExtensions.length < 3) {
  failures.push(
    `read ${proseExtensions.length} prose extensions out of the manager, which cannot be right`,
  );
}

// Every one of them, as a synthetic file, so coverage does not depend on a
// fixture existing for each. The tracked fixtures are checked as well, since
// those are what the walk sees.
const proseFiles = [
  ...proseExtensions.flatMap((ext) => [
    `synthetic/BUILD${ext}`,
    `synthetic/BUILD${ext.toUpperCase()}`,
  ]),
  ...execFileSync("git", ["ls-files", "*BUILD.*"], {
    cwd: repoDir,
    encoding: "utf8",
  })
    .split("\n")
    .filter((f) => proseExtensions.includes(f.slice(f.lastIndexOf(".")))),
];

// A branch config describes its first upgrade, so a branch spanning a build file
// and a source hands the same `managerData` to both. Each file has to be read
// correctly even when the config it is given is about the other one.
// Excluding the record-dependent files: handing one of those a foreign config
// makes it fall back, and the fallback is wrong for them by construction, so
// including one would measure that rather than whether the stamp is scoped.
const crossCheckable = packageFiles.filter(
  (f) => !recordDependent.includes(f.packageFile),
);
const buildFileDeps = crossCheckable.find((f) =>
  f.deps.some((d) => d.managerData?.pantsReadAs === "buildFile"),
);
const sourceDeps = crossCheckable.find((f) =>
  f.deps.some((d) => d.managerData?.pantsReadAs === "source"),
);

if (!buildFileDeps || !sourceDeps) {
  failures.push(
    "no build-file and source pair to cross-check: this check tests nothing",
  );
} else {
  for (const [own, foreign] of [
    [buildFileDeps, sourceDeps],
    [sourceDeps, buildFileDeps],
  ]) {
    const content = readFileSync(resolve(repoDir, own.packageFile), "utf8");
    const foreignConfig = {
      ...managerConfig,
      ...foreign.deps[0],
      packageFile: foreign.packageFile,
    };
    const res = await extractPackageFile(
      content,
      own.packageFile,
      foreignConfig,
    );
    const got = (res?.deps ?? []).map((d) => d.depName).sort();
    const want = own.deps.map((d) => d.depName).sort();
    if (JSON.stringify(got) !== JSON.stringify(want)) {
      failures.push(
        `${own.packageFile}: read as ${JSON.stringify(got)} when handed the config for ${foreign.packageFile}, expected ${JSON.stringify(want)}`,
      );
    }
  }
}

const proseContent = [
  "# Adding a dependency",
  "",
  "```python",
  'python_requirement(name="example", requirements=["evil==9.9.9"])',
  "```",
  "",
].join("\n");

for (const proseFile of proseFiles) {
  const content = proseFile.startsWith("synthetic/")
    ? proseContent
    : readFileSync(resolve(repoDir, proseFile), "utf8");
  const res = await extractPackageFile(content, proseFile, managerConfig);
  if (res !== null) {
    failures.push(
      `${proseFile}: read as a build file, got ${JSON.stringify(res.deps?.map((d) => d.depName))}`,
    );
  }
}

/** A new value of the same shape, so the range stays valid. */
function bump(currentValue) {
  if (/^==/.test(currentValue)) {
    return "==99.9.9";
  }
  if (/^\^/.test(currentValue)) {
    return "^99.9.9";
  }
  if (currentValue.includes(",")) {
    return currentValue.replace(/[\d.]+/, "99.9.9");
  }
  return currentValue.replace(/[\d.]+$/, "99.9.9");
}

for (const packageFile of packageFiles) {
  const original = readFileSync(
    resolve(repoDir, packageFile.packageFile),
    "utf8",
  );

  // `doAutoReplace` writes the file it updates. Restored in a `finally` so that
  // a throw anywhere in the loop cannot leave the repository mutated for the
  // next run to measure.
  try {
    for (const [depIndex, dep] of packageFile.deps.entries()) {
      if (!dep.currentValue || dep.skipReason || dep.depName === "python") {
        continue; // nothing to write, or not a requirement Renovate updates
      }

      const newValue = bump(dep.currentValue);
      // The whole dependency, the way `flattenUpdates` merges it into the
      // branch config. Naming a few fields by hand is how this script came to
      // hide a field the manager depends on.
      const upgrade = {
        ...managerConfig,
        ...dep,
        manager: "pants",
        packageFile: packageFile.packageFile,
        newValue,
        depIndex,
      };

      // The same update from a dependency with no recorded reading, which is
      // the shape a warm extract cache replays: the fingerprint that
      // invalidates it covers this manager's tests and not its implementation.
      // Every file has to survive that except the ones nothing but the record
      // can route, which are derived below rather than assumed.
      //
      // `managerData: undefined` is what strips the record. Spreading a copy of
      // the dependency without the key cannot, because `upgrade` is built with
      // `...dep` and already has it.
      if (!recordDependent.includes(packageFile.packageFile)) {
        degradedChecked += 1;
        try {
          const degraded = await doAutoReplace(
            filterConfig({ ...upgrade, managerData: undefined }, "branch"),
            original,
            false,
          );
          if (degraded === null || degraded === original) {
            failures.push(
              `${packageFile.packageFile}: ${dep.depName} does not update without the recorded reading`,
            );
          }
        } catch (err) {
          failures.push(
            `${packageFile.packageFile}: ${dep.depName} threw ${err.message} without the recorded reading`,
          );
        }
      }

      let updated;
      try {
        updated = await doAutoReplace(
          filterConfig(upgrade, "branch"),
          original,
          false,
        );
      } catch (err) {
        failures.push(
          `${packageFile.packageFile}: ${dep.depName} ${dep.currentValue} -> ${newValue} threw ${err.message}`,
        );
        continue;
      }

      checked += 1;

      if (updated === original) {
        failures.push(
          `${packageFile.packageFile}: ${dep.depName} ${dep.currentValue} -> ${newValue} left the file unchanged`,
        );
        continue;
      }

      if (!updated.includes(newValue)) {
        failures.push(
          `${packageFile.packageFile}: ${dep.depName} update did not write ${newValue}`,
        );
        continue;
      }

      // Exactly one line may move, and it has to be a line that held the text
      // being replaced: a count alone would pass even if the edit landed on an
      // unrelated line.
      const originalLines = original.split("\n");
      const updatedLines = updated.split("\n");
      const changed = originalLines
        .map((line, index) => [index, line])
        .filter(([index, line]) => line !== updatedLines[index]);

      if (changed.length !== 1) {
        failures.push(
          `${packageFile.packageFile}: ${dep.depName} changed ${changed.length} lines, expected 1`,
        );
        continue;
      }

      const [changedIndex, changedLine] = changed[0];
      const anchor = dep.replaceString ?? dep.currentValue;
      if (!changedLine.includes(anchor)) {
        failures.push(
          `${packageFile.packageFile}: ${dep.depName} changed line ${changedIndex}, which does not hold ${anchor}`,
        );
      }
      if (!updatedLines[changedIndex].includes(newValue)) {
        failures.push(
          `${packageFile.packageFile}: ${dep.depName} did not write ${newValue} on the line it changed`,
        );
      }
    }
  } finally {
    writeFileSync(resolve(repoDir, packageFile.packageFile), original);
  }
}

console.log(
  `applied ${checked} updates across ${packageFiles.length} package files`,
);

if (checked !== EXPECTED_UPDATES) {
  failures.push(
    `applied ${checked} updates, expected ${EXPECTED_UPDATES}: a dependency this repository declares is no longer being updated`,
  );
}

// The degraded runs need a floor of their own. Without one, skipping every one
// of them -- by widening the record-dependent set, or by getting the condition
// wrong in any other way -- leaves this script green with no degraded coverage
// at all.
if (degradedChecked !== EXPECTED_DEGRADED_UPDATES) {
  failures.push(
    `applied ${degradedChecked} updates without the recorded reading, expected ${EXPECTED_DEGRADED_UPDATES}`,
  );
}

if (failures.length) {
  console.log("\nFAILURES:");
  for (const failure of failures) {
    console.log(`  - ${failure}`);
  }
  process.exit(1);
}

console.log("every dependency updated in place");
