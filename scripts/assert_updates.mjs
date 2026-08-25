// Applies an update to every dependency this repository declares, using the
// same code path Renovate uses to write a branch, and checks that the right
// text moved. Extraction alone would not catch an update that silently fails.
//
// Usage: node scripts/assert_updates.mjs <path-to-renovate-checkout>

import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const renovateSrc = resolve(process.argv[2] ?? ".renovate-src");
const repoDir = process.cwd();

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

const buildFiles = execFileSync(
  "git",
  ["ls-files", "*BUILD.pants", "*pants_targets.py", "*.build.toml"],
  { cwd: repoDir, encoding: "utf8" },
)
  .split("\n")
  .filter(Boolean);

const packageFiles = await extractAllPackageFiles(managerConfig, buildFiles);

// Prose that the patterns match has to be refused by the single-file entry
// point as well, not only skipped by the walk. That entry point is the
// auto-replace confirmation, and it is the only place a difference between the
// two shows up: a file the walk skips and this one reads is a file Renovate
// would offer to edit and then fail on.
const proseFiles = execFileSync(
  "git",
  ["ls-files", "*BUILD.md", "*BUILD.rst", "*BUILD.markdown"],
  { cwd: repoDir, encoding: "utf8" },
)
  .split("\n")
  .filter(Boolean);

if (!proseFiles.length) {
  failures.push(
    "no prose build file in the repository: this check tests nothing",
  );
}

// A branch config describes its first upgrade, so a branch spanning a build file
// and a source hands the same `managerData` to both. Each file has to be read
// correctly even when the config it is given is about the other one.
const buildFileDeps = packageFiles.find((f) =>
  f.deps.some((d) => d.managerData?.pantsReadAs === "buildFile"),
);
const sourceDeps = packageFiles.find((f) =>
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

for (const proseFile of proseFiles) {
  const content = readFileSync(resolve(repoDir, proseFile), "utf8");
  const res = await extractPackageFile(content, proseFile, managerConfig);
  if (res !== null) {
    failures.push(
      `${proseFile}: read as a build file, got ${JSON.stringify(res.deps?.map((d) => d.depName))}`,
    );
  }
}

const failures = [];
let checked = 0;

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

// Every dependency this repository declares and Renovate can update. A
// regression that stops extracting some of them would otherwise leave this
// script testing less and still exiting zero.
// Files whose content says the wrong thing about what they are, so the recorded
// reading is the only thing that routes them. Listed rather than inferred, so
// that a file joining this list is a deliberate decision.
const RECORD_DEPENDENT = ["record-decides/constraints"];

const EXPECTED_UPDATES = 34;

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
      // Every file has to survive that except the one whose content genuinely
      // says the wrong thing, which nothing but the record can route.
      const { managerData: _noRecord, ...withoutRecord } = dep;
      if (!RECORD_DEPENDENT.includes(packageFile.packageFile)) {
        try {
          const degraded = await doAutoReplace(
            filterConfig(
              { ...upgrade, ...withoutRecord, managerData: undefined },
              "branch",
            ),
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

if (failures.length) {
  console.log("\nFAILURES:");
  for (const failure of failures) {
    console.log(`  - ${failure}`);
  }
  process.exit(1);
}

console.log("every dependency updated in place");
