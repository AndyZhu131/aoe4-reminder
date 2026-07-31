const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const repositoryRoot = path.resolve(__dirname, "..", "..", "..");
const frontendRoot = path.join(repositoryRoot, "src", "frontend");
const releasePackageJson = JSON.parse(
  fs.readFileSync(path.join(repositoryRoot, "package.json"), "utf8"),
);
const releaseVersion = releasePackageJson.version;
const outputDirectory = path.join(repositoryRoot, "release", releaseVersion);
const frontendPackagePath = path.join(frontendRoot, "package.json");
const electronBuilderCli = path.join(
  frontendRoot,
  "node_modules",
  "electron-builder",
  "cli.js",
);

const originalFrontendPackage = fs.readFileSync(frontendPackagePath, "utf8");
const frontendPackage = JSON.parse(originalFrontendPackage);
const frontendVersionChanged = frontendPackage.version !== releaseVersion;

if (frontendVersionChanged) {
  fs.writeFileSync(
    frontendPackagePath,
    `${JSON.stringify({ ...frontendPackage, version: releaseVersion }, null, 2)}\n`,
  );
}

let result;
try {
  result = spawnSync(
    process.execPath,
    [electronBuilderCli, "--win", "nsis", `--config.directories.output=${outputDirectory}`],
    {
      cwd: frontendRoot,
      stdio: "inherit",
    },
  );
} finally {
  if (frontendVersionChanged) {
    fs.writeFileSync(frontendPackagePath, originalFrontendPackage);
  }
}

if (result.error) throw result.error;
process.exit(result.status ?? 1);
