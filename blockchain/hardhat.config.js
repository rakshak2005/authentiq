require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

const AMOY_CHAIN_ID = 80002;
const POLYGON_MAINNET_CHAIN_ID = 137;

const privateKey = process.env.DEPLOYER_PRIVATE_KEY || "";
const accounts = privateKey ? [privateKey] : [];

module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200
      }
    }
  },
  networks: {
    hardhat: {
      chainId: 31337
    },
    localhost: {
      url: "http://127.0.0.1:8545",
      chainId: 31337,
      accounts: [
        "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
      ],
    },
    amoy: {
      url: process.env.AMOY_RPC_URL || "https://rpc-amoy.polygon.technology",
      chainId: AMOY_CHAIN_ID,
      accounts
    }
  },
  etherscan: {
    apiKey: {
      polygonAmoy: process.env.POLYGONSCAN_API_KEY || ""
    }
  },

  /**
   * Guard against accidental deployment to Polygon mainnet.
   * The deploy script also enforces this at runtime.
   */
  verifyBlockGasLimit: false
};

module.exports.AMOY_CHAIN_ID = AMOY_CHAIN_ID;
module.exports.POLYGON_MAINNET_CHAIN_ID = POLYGON_MAINNET_CHAIN_ID;
