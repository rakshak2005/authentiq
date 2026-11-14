#!/usr/bin/env node
/**
 * AUTHENTIQ Groth16 Proof Service (Node.js)
 *
 * Provides proof generation and verification for the ownership commitment
 * circuit using snarkjs and the compiled Groth16 artifacts.
 *
 * Usage:
   node groth16.js prove <fingerprint> <secret> <commitment>
   node groth16.js verify <proof.json> <public.json>
 */

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const SNARKJS = require.resolve("snarkjs/cli.js");
const BUILD_DIR = path.join(__dirname, "..", "build");

const WATSM_PATH = path.join(BUILD_DIR, "ownership.wasm");
const ZKEY_PATH = path.join(BUILD_DIR, "ownership_final.zkey");
const VK_PATH = path.join(BUILD_DIR, "verification_key.json");

function runSnarkjs(args, inputText) {
  const result = execFileSync("node", [SNARKJS, ...args], {
    input: inputText,
    encoding: "utf8",
    maxBuffer: 50 * 1024 * 1024,
  });
  return result.trim();
}

function cmd(cmdName) {
  // snarkjs cli shortcuts
  const shortcuts = {
    "wtns calculate": ["wtns", "calculate"],
    "groth16 prove": ["groth16", "prove"],
    "groth16 verify": ["groth16", "verify"],
    "groth16 fullprove": ["groth16", "fullprove"],
  };
  return shortcuts[cmdName] || cmdName.split(" ");
}

async function prove(fingerprint, secret, commitment) {
  const input = {
    fingerprint: fingerprint,
    secret: secret,
    commitment: commitment,
  };
  const inputPath = path.join(BUILD_DIR, "input.json");
  fs.writeFileSync(inputPath, JSON.stringify(input));

  const proofPath = path.join(BUILD_DIR, "proof.json");
  const publicPath = path.join(BUILD_DIR, "public.json");

  // Use fullprove: calculate witness + generate proof in one step
  runSnarkjs(
    cmd("groth16 fullprove"),
    undefined
  );
  // fullprove needs file arguments, not stdin. Use execFileSync with args.
  const fullproveArgs = [
    inputPath,
    WATSM_PATH,
    ZKEY_PATH,
    proofPath,
    publicPath,
  ];
  execFileSync("node", [SNARKJS, "groth16", "fullprove", ...fullproveArgs], {
    encoding: "utf8",
    maxBuffer: 50 * 1024 * 1024,
  });

  const proof = JSON.parse(fs.readFileSync(proofPath, "utf8"));
  const publicSignals = JSON.parse(fs.readFileSync(publicPath, "utf8"));

  return { proof, public_signals: publicSignals };
}

function verify(proof, publicSignals) {
  const vKey = JSON.parse(fs.readFileSync(VK_PATH, "utf8"));

  // Write proof and public signals to temp files for snarkjs verify
  const proofPath = path.join(BUILD_DIR, "verify_proof.json");
  const publicPath = path.join(BUILD_DIR, "verify_public.json");
  fs.writeFileSync(proofPath, JSON.stringify(proof));
  fs.writeFileSync(publicPath, JSON.stringify(publicSignals));

  const result = execFileSync(
    "node",
    [SNARKJS, "groth16", "verify", VK_PATH, publicPath, proofPath],
    { encoding: "utf8", maxBuffer: 50 * 1024 * 1024 }
  );

  // snarkjs groth16 verify outputs "OK" or "Invalid proof"
  const trimmed = result.trim();
  return trimmed === "OK";
}

const mode = process.argv[2];

if (mode === "prove") {
  const [, , fingerprint, secret, commitment] = process.argv;
  prove(fingerprint, secret, commitment)
    .then((result) => {
      console.log(JSON.stringify(result));
    })
    .catch((err) => {
      console.error(JSON.stringify({ error: err.message }));
      process.exit(1);
    });
} else if (mode === "verify") {
  const [, , proofPath, publicPath] = process.argv;
  const proof = JSON.parse(fs.readFileSync(proofPath, "utf8"));
  const publicSignals = JSON.parse(fs.readFileSync(publicPath, "utf8"));
  const valid = verify(proof, publicSignals);
  console.log(JSON.stringify({ valid }));
} else {
  console.error("Usage: node groth16.js prove <fingerprint> <secret> <commitment>");
  console.error("       node groth16.js verify <proof.json> <public.json>");
  process.exit(1);
}
