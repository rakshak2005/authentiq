include "circomlib_local/poseidon.circom";
include "circomlib_local/comparators.circom";

/**
 * AUTHENTIQ Ownership Commitment Circuit (Groth16)
 *
 * Proves knowledge of a secret opening for a Poseidon commitment:
 *
 *     commitment = Poseidon(fingerprint, secret)
 *
 * Public inputs:
 *   fingerprint - field element derived from SHA-256(file) mod p
 *   commitment  - the Poseidon commitment value
 *
 * Private witness:
 *   secret - the random scalar used to open the commitment
 *
 * NOTE: This circuit does NOT prove anything about SHA-256(file).
 * The fingerprint is treated as an opaque field element. The binding
 * between the file and the fingerprint is enforced outside the circuit
 * by the application layer (server-side SHA-256 verification).
 *
 * Range validation:
 *   All Circom signals are field elements modulo p, so 0 <= x < p is
 *   enforced by construction. We additionally verify that fingerprint
 *   and secret are non-zero to avoid degenerate witnesses.
 */
template OwnershipCommitment() {
    signal input fingerprint;
    signal input secret;
    signal input commitment;

    // Non-degeneracy: fingerprint must not be zero
    component fpCheck = IsZero();
    fpCheck.in <== fingerprint;

    // Non-degeneracy: secret must not be zero
    component secretCheck = IsZero();
    secretCheck.in <== secret;

    // Poseidon hash of (fingerprint, secret)
    component hasher = Poseidon(2);
    hasher.inputs[0] <== fingerprint;
    hasher.inputs[1] <== secret;

    // Constrain that the computed commitment matches the provided public commitment
    hasher.out === commitment;

    // fingerprint and secret must not be zero
    fpCheck.out === 0;
    secretCheck.out === 0;
}

component main {public [fingerprint, commitment]} = OwnershipCommitment();
