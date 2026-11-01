#!/usr/bin/env node
// Load only client configuration from the root .env, preserving explicit overrides.
const { readFileSync } = require("node:fs");
const { parseEnv } = require("node:util");
const { resolve } = require("node:path");
const { spawn } = require("node:child_process");

const mobile = resolve(__dirname, "../mobile");
try {
  const values = process.env.EXPO_NO_DOTENV === "1"
    ? {}
    : parseEnv(readFileSync(resolve(__dirname, "../.env"), "utf8"));
  for (const [key, value] of Object.entries(values)) {
    if (key.startsWith("EXPO_PUBLIC_") && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
process.env.EXPO_NO_DOTENV = "1";
const child = spawn(process.execPath, [
  require.resolve("expo/bin/cli", { paths: [mobile] }),
  ...process.argv.slice(2),
], { cwd: mobile, env: process.env, stdio: "inherit" });
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("error", (error) => { console.error(error.message); process.exitCode = 1; });
child.on("exit", (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0); });
