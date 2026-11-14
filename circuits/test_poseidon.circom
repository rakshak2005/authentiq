include "../node_modules/circomlib/circuits/poseidon.circom";

template TestPoseidon() {
    signal input a;
    signal input b;
    signal output c;

    component hasher = Poseidon(2);
    hasher.inputs[0] <== a;
    hasher.inputs[1] <== b;
    c <== hasher.out;
}

component main = TestPoseidon();
