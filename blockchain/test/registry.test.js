const { expect } = require("chai");
const { ethers } = require("hardhat");
const { anyValue } = require("@nomicfoundation/hardhat-chai-matchers/withArgs");

const VALID_DIGEST = "a".repeat(64);
const UPPERCASE_DIGEST = "A".repeat(64);
const MIXED_DIGEST = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

describe("AuthentiqRegistry", function () {
  async function deployFixture() {
    const [owner, writer, outsider] = await ethers.getSigners();
    const factory = await ethers.getContractFactory("AuthentiqRegistry");
    const registry = await factory.deploy();
    await registry.waitForDeployment();
    return { registry, owner, writer, outsider };
  }

  describe("deployment", function () {
    it("authorizes the deployer as the first writer and owner", async function () {
      const { registry, owner } = await deployFixture();
      expect(await registry.owner()).to.equal(owner.address);
      expect(await registry.writers(owner.address)).to.equal(true);
    });
  });

  describe("recordEvent", function () {
    it("records an event with the backend-compatible signature", async function () {
      const { registry, owner } = await deployFixture();

      await expect(registry.recordEvent("reg_001", "registration.created", VALID_DIGEST, "reg_001"))
        .to.emit(registry, "RecordEvent")
        .withArgs("reg_001", "registration.created", VALID_DIGEST, "reg_001", owner.address, anyValue, 1);

      const stored = await registry.getRecord("reg_001");
      expect(stored.recordType).to.equal("registration.created");
      expect(stored.payloadDigest).to.equal(VALID_DIGEST);
      expect(stored.entityId).to.equal("reg_001");
      expect(stored.submitter).to.equal(owner.address);
      expect(await registry.totalRecords()).to.equal(1);
    });

    it("accepts uppercase and mixed-case hex digests", async function () {
      const { registry } = await deployFixture();

      await registry.recordEvent("reg_upper", "registration.created", UPPERCASE_DIGEST, "reg_upper");
      await registry.recordEvent("reg_mixed", "registration.created", MIXED_DIGEST, "reg_mixed");

      expect(await registry.revisionCounts("reg_upper")).to.equal(1);
      expect(await registry.revisionCounts("reg_mixed")).to.equal(1);
    });

    it("increments revisions for repeated record identifiers", async function () {
      const { registry } = await deployFixture();
      await registry.recordEvent("reg_001", "registration.created", VALID_DIGEST, "reg_001");
      await registry.recordEvent("reg_001", "version.created", "b".repeat(64), "reg_001");
      await registry.recordEvent("reg_001", "provenance.recorded", "c".repeat(64), "reg_001");

      expect(await registry.revisionCounts("reg_001")).to.equal(3);
      expect(await registry.totalRecords()).to.equal(3);
    });

    it("stores the latest record for a repeated identifier", async function () {
      const { registry } = await deployFixture();
      await registry.recordEvent("reg_001", "registration.created", VALID_DIGEST, "reg_001");
      await registry.recordEvent("reg_001", "version.created", "b".repeat(64), "reg_001");

      const stored = await registry.getRecord("reg_001");
      expect(stored.recordType).to.equal("version.created");
      expect(stored.payloadDigest).to.equal("b".repeat(64));
    });

    it("exposes each revision independently via getRecordRevision", async function () {
      const { registry } = await deployFixture();
      await registry.recordEvent("reg_001", "registration.created", VALID_DIGEST, "reg_001");
      await registry.recordEvent("reg_001", "version.created", "b".repeat(64), "reg_001");
      await registry.recordEvent("reg_001", "provenance.recorded", "c".repeat(64), "reg_001");

      const first = await registry.getRecordRevision("reg_001", 1);
      expect(first.recordType).to.equal("registration.created");
      expect(first.payloadDigest).to.equal(VALID_DIGEST);
      expect(first.revision).to.be.an("undefined"); // struct field not exposed directly; checked via recordType

      const second = await registry.getRecordRevision("reg_001", 2);
      expect(second.recordType).to.equal("version.created");
      expect(second.payloadDigest).to.equal("b".repeat(64));

      const third = await registry.getRecordRevision("reg_001", 3);
      expect(third.recordType).to.equal("provenance.recorded");
      expect(third.payloadDigest).to.equal("c".repeat(64));

      const latest = await registry.getRecordRevision("reg_001", await registry.revisionCounts("reg_001"));
      expect(latest.recordType).to.equal("provenance.recorded");
    });

    it("returns zeroed record for a revision that does not exist", async function () {
      const { registry } = await deployFixture();
      const empty = await registry.getRecordRevision("reg_missing", 1);
      expect(empty.recordType).to.equal("");
      expect(empty.payloadDigest).to.equal("");
      expect(empty.entityId).to.equal("");
      expect(empty.submitter).to.equal(ethers.ZeroAddress);
      expect(empty.timestamp).to.equal(0);
    });

    it("tracks independent revision counts per record identifier", async function () {
      const { registry } = await deployFixture();
      await registry.recordEvent("reg_a", "registration.created", VALID_DIGEST, "reg_a");
      await registry.recordEvent("reg_a", "version.created", "b".repeat(64), "reg_a");
      await registry.recordEvent("reg_b", "registration.created", "c".repeat(64), "reg_b");

      expect(await registry.revisionCounts("reg_a")).to.equal(2);
      expect(await registry.revisionCounts("reg_b")).to.equal(1);
      expect(await registry.totalRecords()).to.equal(3);
    });
  });

  describe("input validation", function () {
    it("rejects empty payload digests", async function () {
      const { registry } = await deployFixture();
      await expect(registry.recordEvent("reg_001", "registration.created", "", "reg_001"))
        .to.be.revertedWithCustomError(registry, "EmptyPayloadDigest");
    });

    it("rejects payload digests shorter than 64 characters", async function () {
      const { registry } = await deployFixture();
      await expect(registry.recordEvent("reg_001", "registration.created", "short", "reg_001"))
        .to.be.revertedWithCustomError(registry, "InvalidPayloadDigest");
    });

    it("rejects payload digests longer than 64 characters", async function () {
      const { registry } = await deployFixture();
      await expect(registry.recordEvent("reg_001", "registration.created", "a".repeat(65), "reg_001"))
        .to.be.revertedWithCustomError(registry, "InvalidPayloadDigest");
    });

    it("rejects payload digests containing non-hex characters", async function () {
      const { registry } = await deployFixture();
      const invalid = "g".repeat(64);
      await expect(registry.recordEvent("reg_001", "registration.created", invalid, "reg_001"))
        .to.be.revertedWithCustomError(registry, "InvalidPayloadDigest");
    });

    it("rejects payload digests containing whitespace", async function () {
      const { registry } = await deployFixture();
      const invalid = " ".repeat(64);
      await expect(registry.recordEvent("reg_001", "registration.created", invalid, "reg_001"))
        .to.be.revertedWithCustomError(registry, "InvalidPayloadDigest");
    });

    it("rejects empty record identifiers", async function () {
      const { registry } = await deployFixture();
      await expect(registry.recordEvent("", "registration.created", VALID_DIGEST, "reg_001"))
        .to.be.revertedWithCustomError(registry, "InvalidRecordId");
    });
  });

  describe("writer authorization", function () {
    it("only allows writers to record events", async function () {
      const { registry, writer, outsider } = await deployFixture();

      await expect(registry.connect(outsider).recordEvent("reg_001", "registration.created", VALID_DIGEST, "reg_001"))
        .to.be.revertedWithCustomError(registry, "NotWriter");

      await registry.setWriter(writer.address, true);
      await expect(registry.connect(writer).recordEvent("reg_001", "registration.created", VALID_DIGEST, "reg_001"))
        .to.emit(registry, "RecordEvent");
    });

    it("only allows the owner to add writers", async function () {
      const { registry, writer, outsider } = await deployFixture();

      await expect(registry.connect(outsider).setWriter(writer.address, true))
        .to.be.revertedWithCustomError(registry, "NotOwner");

      await registry.setWriter(writer.address, true);
      expect(await registry.writers(writer.address)).to.equal(true);

      await registry.setWriter(writer.address, false);
      expect(await registry.writers(writer.address)).to.equal(false);
    });

    it("prevents a removed writer from recording events", async function () {
      const { registry, writer } = await deployFixture();
      await registry.setWriter(writer.address, true);
      await registry.setWriter(writer.address, false);

      await expect(registry.connect(writer).recordEvent("reg_001", "registration.created", VALID_DIGEST, "reg_001"))
        .to.be.revertedWithCustomError(registry, "NotWriter");
    });
  });

  describe("ownership administration", function () {
    it("allows the owner to transfer ownership to a non-zero address", async function () {
      const { registry, owner, writer } = await deployFixture();

      await expect(registry.connect(owner).transferOwnership(writer.address))
        .to.emit(registry, "OwnershipTransferred")
        .withArgs(owner.address, writer.address);

      expect(await registry.owner()).to.equal(writer.address);
    });

    it("rejects transfer of ownership to the zero address", async function () {
      const { registry, owner } = await deployFixture();
      await expect(registry.connect(owner).transferOwnership(ethers.ZeroAddress))
        .to.be.revertedWithCustomError(registry, "InvalidNewOwner");
    });

    it("rejects ownership transfer from a non-owner", async function () {
      const { registry, outsider } = await deployFixture();
      await expect(registry.connect(outsider).transferOwnership(outsider.address))
        .to.be.revertedWithCustomError(registry, "NotOwner");
    });

    it("new owner can add writers after transfer", async function () {
      const { registry, owner, writer } = await deployFixture();
      await registry.connect(owner).transferOwnership(writer.address);

      const newWriter = (await ethers.getSigners())[3];
      await registry.connect(writer).setWriter(newWriter.address, true);
      expect(await registry.writers(newWriter.address)).to.equal(true);
    });
  });

  describe("event emission", function () {
    it("emits WriterChanged when a writer is added or removed", async function () {
      const { registry, writer } = await deployFixture();

      await expect(registry.setWriter(writer.address, true))
        .to.emit(registry, "WriterChanged")
        .withArgs(writer.address, true);

      await expect(registry.setWriter(writer.address, false))
        .to.emit(registry, "WriterChanged")
        .withArgs(writer.address, false);
    });

    it("emits RecordEvent with the correct revision sequence", async function () {
      const { registry, owner } = await deployFixture();

      await expect(registry.recordEvent("reg_001", "registration.created", VALID_DIGEST, "reg_001"))
        .to.emit(registry, "RecordEvent")
        .withArgs("reg_001", "registration.created", VALID_DIGEST, "reg_001", owner.address, anyValue, 1);

      await expect(registry.recordEvent("reg_001", "version.created", "b".repeat(64), "reg_001"))
        .to.emit(registry, "RecordEvent")
        .withArgs("reg_001", "version.created", "b".repeat(64), "reg_001", owner.address, anyValue, 2);
    });

    it("emits OwnershipTransferred on transferOwnership", async function () {
      const { registry, owner, writer } = await deployFixture();
      await expect(registry.connect(owner).transferOwnership(writer.address))
        .to.emit(registry, "OwnershipTransferred")
        .withArgs(owner.address, writer.address);
    });
  });
});
