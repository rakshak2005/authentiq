#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const circuitsDir = path.join(__dirname, "..");
const buildDir = path.join(circuitsDir, "build");
const circom = process.platform === "win32" ? "circom.exe" : "circom";

fs.mkdirSync(buildDir, { recursive: true });

function compile(source, outputName) {
  execFileSync(
    circom,
    [source, "--r1cs", "--wasm", "--sym", "-o", "build"],
    { cwd: circuitsDir, stdio: "inherit" }
  );

  const generatedWasm = path.join(
    buildDir,
    `${path.basename(source, ".circom")}_js`,
    `${path.basename(source, ".circom")}.wasm`
  );
  fs.copyFileSync(generatedWasm, path.join(buildDir, outputName));
}

compile("ownership.circom", "ownership.wasm");
compile("compute_commitment.circom", "commitment.wasm");
