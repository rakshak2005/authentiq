const hre = require("hardhat");
const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log(`Deploying with account: ${deployer.address}`);

  const factory = await hre.ethers.getContractFactory("AuthentiqRegistry");
  const registry = await factory.deploy();

  const address = await registry.getAddress();
  const deployTx = registry.deploymentTransaction();
  const txHash = deployTx ? deployTx.hash : null;

  // Poll for contract code to confirm deployment (local node mines immediately)
  let code = await hre.ethers.provider.getCode(address);
  let attempts = 0;
  while (code === "0x" || code === "0x0") {
    if (attempts >= 60) {
      throw new Error(`Contract not deployed at ${address} after 60s`);
    }
    await new Promise((r) => setTimeout(r, 1000));
    code = await hre.ethers.provider.getCode(address);
    attempts += 1;
  }
  console.log(`Contract deployed at ${address} (tx: ${txHash})`);

  const artifact = {
    contract: "AuthentiqRegistry",
    address,
    chainId: 31337,
    deployer: deployer.address,
    transactionHash: txHash,
    blockNumber: await hre.ethers.provider.getBlockNumber(),
    network: "localhost",
    deployedAt: new Date().toISOString(),
  };

  const deploymentsDir = path.join(__dirname, "..", "deployments");
  fs.mkdirSync(deploymentsDir, { recursive: true });
  const destination = path.join(deploymentsDir, "31337.json");
  fs.writeFileSync(destination, JSON.stringify(artifact, null, 2));

  console.log(JSON.stringify(artifact, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
