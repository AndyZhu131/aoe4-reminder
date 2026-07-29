const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const repositoryRoot = path.resolve(__dirname, "..", "..", "..");
const frontendRoot = path.join(repositoryRoot, "src", "frontend");
const packageJson = JSON.parse(
  fs.readFileSync(path.join(frontendRoot, "package.json"), "utf8"),
);
const outputDirectory = path.join(repositoryRoot, "release", packageJson.version);
const electronBuilderCli = path.join(
  frontendRoot,
  "node_modules",
  "electron-builder",
  "cli.js",
);

const result = spawnSync(
  process.execPath,
  [electronBuilderCli, "--win", "nsis", `--config.directories.output=${outputDirectory}`],
  {
    cwd: frontendRoot,
    stdio: "inherit",
  },
);

if (result.error) throw result.error;
process.exit(result.status ?? 1);
