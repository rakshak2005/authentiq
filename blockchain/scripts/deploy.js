const fs = require("node:fs");
const path = require("node:path");
const hre = require("hardhat");

const { AMOY_CHAIN_ID, POLYGON_MAINNET_CHAIN_ID } = require("../hardhat.config");

// Minimum test POL balance required for deployment (in wei).
// 0.001 POL is a conservative floor; actual deployment costs less.
const MIN_BALANCE_WEI = hre.ethers.parseEther("0.001");

function requireEnv(name) {
  const value = process.env[name];
  if (!value || value.trim() === "") {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value.trim();
}

async function main() {
  // --- 1. Determine the target network ---
  const networkName = hre.network.name;
  const network = await hre.ethers.provider.getNetwork();
  const chainId = Number(network.chainId);

  console.log(`Connected network: ${networkName} (chainId: ${chainId})`);

  // --- 2. Guard against Polygon mainnet ---
  if (chainId === POLYGON_MAINNET_CHAIN_ID) {
    throw new Error(
      "Refusing to deploy to Polygon mainnet (chainId 137). This script only supports Amoy testnet (chainId 80002)."
    );
  }

  // --- 3. Validate Amoy network configuration ---
  if (chainId !== AMOY_CHAIN_ID && networkName !== "hardhat") {
    throw new Error(
      `Unexpected chainId ${chainId}. Expected ${AMOY_CHAIN_ID} (Amoy testnet) or local Hardhat network.`
    );
  }

  const isAmoy = chainId === AMOY_CHAIN_ID;
  const rpcUrl = process.env.AMOY_RPC_URL;
  if (isAmoy && !rpcUrl) {
    throw new Error(
      "AMOY_RPC_URL environment variable is required for Amoy deployment."
    );
  }

  // --- 4. Check deployer account ---
  requireEnv("DEPLOYER_PRIVATE_KEY");
  const [deployer] = await hre.ethers.getSigners();
  console.log(`Deployer address: ${deployer.address}`);

  // --- 5. Check deployer test POL balance ---
  const balance = await hre.ethers.provider.getBalance(deployer.address);
  const balanceEth = hre.ethers.formatEther(balance);
  console.log(`Deployer balance: ${balanceEth} POL`);

  if (balance === 0n) {
    throw new Error(
      `Deployer ${deployer.address} has zero POL balance. Fund the account on Amoy testnet before deploying.`
    );
  }

  if (isAmoy && balance < MIN_BALANCE_WEI) {
    console.warn(
      `WARNING: Deployer balance (${balanceEth} POL) is below the recommended minimum (0.001 POL). Deployment may fail due to insufficient gas.`
    );
  }

  // --- 6. Deploy the AuthentiqRegistry contract ---
  console.log("Deploying AuthentiqRegistry...");
  const factory = await hre.ethers.getContractFactory("AuthentiqRegistry");
  const registry = await factory.deploy();
  await registry.waitForDeployment();

  // --- 7. Capture deployment transaction hash ---
  const deployTx = registry.deploymentTransaction();
  const txHash = deployTx ? deployTx.hash : null;
  if (!txHash) {
    throw new Error("Failed to capture deployment transaction hash.");
  }

  console.log(`Deployment transaction: ${txHash}`);
  console.log("Waiting for deployment confirmation...");

  // --- 8. Wait for deployment confirmation ---
  // waitForDeployment() already confirms, but we explicitly wait on the tx for finality.
  const receipt = await hre.ethers.provider.getTransactionReceipt(txHash);
  if (!receipt) {
    throw new Error(`Deployment transaction receipt not found: ${txHash}`);
  }
  if (receipt.status !== 1) {
    throw new Error(`Deployment transaction failed (status: ${receipt.status}): ${txHash}`);
  }

  const address = await registry.getAddress();
  const confirmedChainId = Number((await hre.ethers.provider.getNetwork()).chainId);

  // --- 9. Save deployment artifact ---
  const payload = {
    contract: "AuthentiqRegistry",
    address,
    chainId: confirmedChainId,
    deployer: deployer.address,
    transactionHash: txHash,
    blockNumber: receipt.blockNumber,
    deployedAt: new Date().toISOString(),
    network: isAmoy ? "amoy" : "hardhat"
  };

  const deploymentsDir = path.join(__dirname, "..", "deployments");
  fs.mkdirSync(deploymentsDir, { recursive: true });
  const destination = path.join(deploymentsDir, `${confirmedChainId}.json`);
  fs.writeFileSync(destination, JSON.stringify(payload, null, 2));

  console.log("\n=== Deployment complete ===");
  console.log(JSON.stringify(payload, null, 2));
  console.log(`\nArtifact saved to: ${destination}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
