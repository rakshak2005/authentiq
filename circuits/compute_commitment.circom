include "circomlib_local/poseidon.circom";

template ComputeCommitment() {
    signal input fingerprint;
    signal input secret;
    signal output commitment;

    component hasher = Poseidon(2);
    hasher.inputs[0] <== fingerprint;
    hasher.inputs[1] <== secret;
    commitment <== hasher.out;
}

component main = ComputeCommitment();
