// Applies an update to every dependency this repository declares, using the
// same code path Renovate uses to write a branch, and checks that the right
// text moved. Extraction alone would not catch an update that silently fails.
//
// Usage: node scripts/assert_updates.mjs <path-to-renovate-checkout>

import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const renovateSrc = resolve(process.argv[2] ?? '.renovate-src');
const repoDir = process.cwd();

const { GlobalConfig } = await import(
  `${renovateSrc}/lib/config/global.ts`
);
const { extractAllPackageFiles } = await import(
  `${renovateSrc}/lib/modules/manager/pants/index.ts`
);
const { doAutoReplace } = await import(
  `${renovateSrc}/lib/workers/repository/update/branch/auto-replace.ts`
);

GlobalConfig.set({ localDir: repoDir });

const buildFiles = execFileSync(
  'git',
  ['ls-files', '*BUILD.pants', '*pants_targets.py'],
  { cwd: repoDir, encoding: 'utf8' },
)
  .split('\n')
  .filter(Boolean);

const packageFiles = await extractAllPackageFiles({}, buildFiles);

/** A new value of the same shape, so the range stays valid. */
function bump(currentValue) {
  if (/^==/.test(currentValue)) {
    return '==99.9.9';
  }
  if (/^\^/.test(currentValue)) {
    return '^99.9.9';
  }
  if (currentValue.includes(',')) {
    return currentValue.replace(/[\d.]+/, '99.9.9');
  }
  return currentValue.replace(/[\d.]+$/, '99.9.9');
}

const failures = [];
let checked = 0;

for (const packageFile of packageFiles) {
  const original = readFileSync(resolve(repoDir, packageFile.packageFile), 'utf8');

  for (const [depIndex, dep] of packageFile.deps.entries()) {
    if (!dep.currentValue || dep.skipReason || dep.depName === 'python') {
      continue; // nothing to write, or not a requirement Renovate updates
    }

    const newValue = bump(dep.currentValue);
    const upgrade = {
      manager: 'pants',
      packageFile: packageFile.packageFile,
      depName: dep.depName,
      currentValue: dep.currentValue,
      replaceString: dep.replaceString,
      depType: dep.depType,
      newValue,
      depIndex,
    };

    let updated;
    try {
      updated = await doAutoReplace(upgrade, original, false);
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

    // Exactly one occurrence may move: a build file can pin the same
    // requirement in several targets, and only the target being updated
    // should change.
    const changedLines = original
      .split('\n')
      .filter((line, index) => line !== updated.split('\n')[index]);
    if (changedLines.length !== 1) {
      failures.push(
        `${packageFile.packageFile}: ${dep.depName} changed ${changedLines.length} lines, expected 1`,
      );
    }
  }

  // `doAutoReplace` writes the file it updates, the same as it does when
  // Renovate builds a branch, so put the original back.
  writeFileSync(resolve(repoDir, packageFile.packageFile), original);
}

console.log(`applied ${checked} updates across ${packageFiles.length} package files`);

if (failures.length) {
  console.log('\nFAILURES:');
  for (const failure of failures) {
    console.log(`  - ${failure}`);
  }
  process.exit(1);
}

console.log('every dependency updated in place');
