// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract AuthentiqRegistry {
    struct Record {
        string recordType;
        string payloadDigest;
        string entityId;
        address submitter;
        uint256 timestamp;
    }

    address public owner;
    uint256 public totalRecords;
    mapping(address => bool) public writers;
    mapping(string => Record) public latestRecords;
    mapping(string => mapping(uint256 => Record)) public recordRevisions;
    mapping(string => uint256) public revisionCounts;

    event RecordEvent(
        string recordId,
        string recordType,
        string payloadDigest,
        string entityId,
        address indexed submitter,
        uint256 timestamp,
        uint256 revision
    );

    event WriterChanged(address indexed writer, bool allowed);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    error NotOwner();
    error NotWriter();
    error EmptyPayloadDigest();
    error InvalidPayloadDigest();
    error InvalidRecordId();
    error InvalidNewOwner();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyWriter() {
        if (!writers[msg.sender]) revert NotWriter();
        _;
    }

    constructor() {
        owner = msg.sender;
        writers[msg.sender] = true;
        emit WriterChanged(msg.sender, true);
    }

    function setWriter(address writer, bool allowed) external onlyOwner {
        writers[writer] = allowed;
        emit WriterChanged(writer, allowed);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidNewOwner();
        address previousOwner = owner;
        owner = newOwner;
        emit OwnershipTransferred(previousOwner, newOwner);
    }

    function recordEvent(
        string calldata recordId,
        string calldata recordType,
        string calldata payloadDigest,
        string calldata entityId
    ) external onlyWriter {
        if (bytes(recordId).length == 0) revert InvalidRecordId();
        _validateDigest(payloadDigest);
        uint256 revision = revisionCounts[recordId] + 1;
        revisionCounts[recordId] = revision;
        totalRecords += 1;
        Record memory record = Record({
            recordType: recordType,
            payloadDigest: payloadDigest,
            entityId: entityId,
            submitter: msg.sender,
            timestamp: block.timestamp
        });
        latestRecords[recordId] = record;
        recordRevisions[recordId][revision] = record;
        emit RecordEvent(
            recordId,
            recordType,
            payloadDigest,
            entityId,
            msg.sender,
            block.timestamp,
            revision
        );
    }

    function getRecord(string calldata recordId) external view returns (Record memory) {
        return latestRecords[recordId];
    }

    function getRecordRevision(string calldata recordId, uint256 revision)
        external
        view
        returns (Record memory)
    {
        return recordRevisions[recordId][revision];
    }

    function _validateDigest(string calldata digest) internal pure {
        bytes memory d = bytes(digest);
        if (d.length == 0) revert EmptyPayloadDigest();
        if (d.length != 64) revert InvalidPayloadDigest();
        for (uint256 i = 0; i < 64; i++) {
            if (
                !(d[i] >= 0x30 && d[i] <= 0x39) &&
                !(d[i] >= 0x41 && d[i] <= 0x46) &&
                !(d[i] >= 0x61 && d[i] <= 0x66)
            ) {
                revert InvalidPayloadDigest();
            }
        }
    }
}
