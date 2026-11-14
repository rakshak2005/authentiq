#!/usr/bin/env node
/**
 * AUTHENTIQ Groth16 Proof Pipeline Tests
 *
 * Tests the complete Groth16 proof pipeline for the ownership commitment
 * circuit:
 *   commitment = Poseidon(fingerprint, secret)
 *
 * Public inputs: fingerprint, commitment
 * Private witness: secret
 *
 * NOTE: This circuit does NOT prove SHA-256(file). The fingerprint is an
 * opaque field element. File-to-fingerprint binding is enforced by the
 * application layer.
 */

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const SNARKJS = path.join(__dirname, "..", "node_modules", "snarkjs", "cli.js");
const BUILD_DIR = path.join(__dirname, "..", "build");

const OWNERSHIP_WASM = path.join(BUILD_DIR, "ownership.wasm");
const OWNERSHIP_ZKEY = path.join(BUILD_DIR, "ownership_final.zkey");
const VK_PATH = path.join(BUILD_DIR, "verification_key.json");
const COMMITMENT_WASM = path.join(BUILD_DIR, "commitment.wasm");

// BN254 scalar field prime
const P =
  21888242871839275222246405745257275088548364400416034343698204186575808495617n;

let passed = 0;
let failed = 0;

function assert(condition, message) {
  if (condition) {
    passed++;
    console.log(`  PASS: ${message}`);
  } else {
    failed++;
    console.log(`  FAIL: ${message}`);
  }
}

function runSnarkjs(args) {
  return execFileSync("node", [SNARKJS, ...args], {
    encoding: "utf8",
    maxBuffer: 50 * 1024 * 1024,
  }).trim();
}

function computePoseidon(fingerprintDec, secretDec) {
  const inputPath = path.join(BUILD_DIR, "test_input_commitment.json");
  const witnessPath = path.join(BUILD_DIR, "test_witness_commitment.wtns");
  const witnessJsonPath = path.join(BUILD_DIR, "test_witness_commitment.json");

  fs.writeFileSync(
    inputPath,
    JSON.stringify({ fingerprint: fingerprintDec, secret: secretDec })
  );

  execFileSync(
    "node",
    [SNARKJS, "wtns", "calculate", COMMITMENT_WASM, inputPath, witnessPath],
    { encoding: "utf8", maxBuffer: 50 * 1024 * 1024 }
  );

  execFileSync(
    "node",
    [SNARKJS, "wtns", "export", "json", witnessPath, witnessJsonPath],
    { encoding: "utf8", maxBuffer: 50 * 1024 * 1024 }
  );

  const witness = JSON.parse(fs.readFileSync(witnessJsonPath, "utf8"));
  // witness[1] is the Poseidon output (commitment)
  return witness[1];
}

function generateProof(fingerprintDec, secretDec, commitmentDec) {
  const inputPath = path.join(BUILD_DIR, "test_input_ownership.json");
  const proofPath = path.join(BUILD_DIR, "test_proof.json");
  const publicPath = path.join(BUILD_DIR, "test_public.json");

  fs.writeFileSync(
    inputPath,
    JSON.stringify({
      fingerprint: fingerprintDec,
      commitment: commitmentDec,
      secret: secretDec,
    })
  );

  execFileSync(
    "node",
    [
      SNARKJS,
      "groth16",
      "fullprove",
      inputPath,
      OWNERSHIP_WASM,
      OWNERSHIP_ZKEY,
      proofPath,
      publicPath,
    ],
    { encoding: "utf8", maxBuffer: 50 * 1024 * 1024 }
  );

  const proof = JSON.parse(fs.readFileSync(proofPath, "utf8"));
  const publicSignals = JSON.parse(fs.readFileSync(publicPath, "utf8"));

  return { proof, publicSignals };
}

function verifyProof(proof, publicSignals) {
  const proofPath = path.join(BUILD_DIR, "test_verify_proof.json");
  const publicPath = path.join(BUILD_DIR, "test_verify_public.json");

  fs.writeFileSync(proofPath, JSON.stringify(proof));
  fs.writeFileSync(publicPath, JSON.stringify(publicSignals));

  try {
    const result = execFileSync(
      "node",
      [SNARKJS, "groth16", "verify", VK_PATH, publicPath, proofPath],
      { encoding: "utf8", maxBuffer: 50 * 1024 * 1024 }
    );
    const out = result.trim();
    return out.includes("OK!") || out.includes("OK");
  } catch (err) {
    // snarkjs exits with code 1 for invalid proofs
    return false;
  }
}

// ---------------------------------------------------------------------------
// Test 1: Valid proof generation and verification
// ---------------------------------------------------------------------------
console.log("\n=== Test 1: Valid proof ===");

const fp1 = "1";
const sec1 = "2";
const comm1 = computePoseidon(fp1, sec1);
console.log(`  fingerprint=${fp1}, secret=${sec1}`);
console.log(`  commitment=${comm1}`);

const result1 = generateProof(fp1, sec1, comm1);
assert(result1.proof !== undefined, "Valid proof generated");
assert(result1.publicSignals !== undefined, "Public signals generated");
assert(
  verifyProof(result1.proof, result1.publicSignals),
  "Valid proof verifies as OK"
);

// ---------------------------------------------------------------------------
// Test 2: Wrong commitment (tampered commitment)
// ---------------------------------------------------------------------------
console.log("\n=== Test 2: Wrong commitment ===");

try {
  const wrongComm = (BigInt(comm1) + 1n) % P;
  const result2 = generateProof(fp1, sec1, wrongComm.toString());
  const valid2 = verifyProof(result2.proof, result2.publicSignals);
  assert(!valid2, "Wrong commitment proof fails verification");
} catch (err) {
  assert(true, "Wrong commitment proof generation or verification failed (expected)");
}

// ---------------------------------------------------------------------------
// Test 3: Wrong secret
// ---------------------------------------------------------------------------
console.log("\n=== Test 3: Wrong secret ===");

try {
  const wrongSec = (BigInt(sec1) + 1n) % P;
  const wrongComm = computePoseidon(fp1, wrongSec.toString());
  // Use the ORIGINAL commitment with wrong secret
  const result3 = generateProof(fp1, wrongSec.toString(), comm1);
  const valid3 = verifyProof(result3.proof, result3.publicSignals);
  assert(!valid3, "Wrong secret proof fails verification");
} catch (err) {
  assert(true, "Wrong secret proof generation or verification failed (expected)");
}

// ---------------------------------------------------------------------------
// Test 4: Tampered fingerprint
// ---------------------------------------------------------------------------
console.log("\n=== Test 4: Tampered fingerprint ===");

try {
  const wrongFp = (BigInt(fp1) + 1n) % P;
  const result4 = generateProof(wrongFp.toString(), sec1, comm1);
  const valid4 = verifyProof(result4.proof, result4.publicSignals);
  assert(!valid4, "Tampered fingerprint proof fails verification");
} catch (err) {
  assert(true, "Tampered fingerprint proof generation or verification failed (expected)");
}

// ---------------------------------------------------------------------------
// Test 5: Multiple independent proofs have different commitments
// ---------------------------------------------------------------------------
console.log("\n=== Test 5: Independent commitments ===");

const fp2 = "3";
const sec2 = "4";
const comm2 = computePoseidon(fp2, sec2);
assert(comm1 !== comm2, "Different (fingerprint, secret) pairs produce different commitments");

// ---------------------------------------------------------------------------
// Test 6: Re-verification with correct public signals succeeds
// ---------------------------------------------------------------------------
console.log("\n=== Test 6: Re-verification ===");

const valid6 = verifyProof(result1.proof, result1.publicSignals);
assert(valid6, "Re-verification of valid proof succeeds");

// ---------------------------------------------------------------------------
// Test 7: Cross-verification fails (proof from one input vs public signals of another)
// ---------------------------------------------------------------------------
console.log("\n=== Test 7: Cross-verification ===");

const valid7 = verifyProof(result1.proof, { ...result1.publicSignals, fingerprint: fp2 });
assert(!valid7, "Cross-verification with mismatched public signals fails");

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n=== Results: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
