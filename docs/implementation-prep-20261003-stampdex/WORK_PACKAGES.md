# PROTO-SRC101-001 — preserve scalar SRC-101 ownership updates

## Scope and evidence status

This is a **comment-only implementation preparation** for `bitcoinuniverseio/btc_stamps` at commit `8666d779d23caf418edb2c78262a0338b7314b7f` (declared version 1.9.3), supporting the StampDEX mainnet review. No executable source is changed, and no upgrade, database migration, ownership backfill, deployment, or transaction is authorized by this document.

| Question | Status | Evidence |
| --- | --- | --- |
| Does the pinned custom owner updater handle an already-valid scalar transfer? | **FAIL** | An isolated extraction of its exact token validator/helpers and owner updater accepts `YWxpY2U=` as scalar `alice`, then raises `IndexError: string index out of range` before calling the writer. |
| Does the compared official updater handle the same record? | **PASS — isolated function comparison only** | Official 1.9.5 returns one intact owner row with the same scalar identity. This does not certify its entire SRC-101 implementation. |
| Does the live server run this custom commit? | **BLOCKED / unobserved** | The server was unavailable. A current GitHub branch is not deployment evidence. |
| Has the full parser, SQL transaction, block replay, or native network lifecycle been tested? | **BLOCKED / unexecuted** | The diagnostic has no running indexer, database, Bitcoin node, or funded wallet. |
| Does this preparation change executable behavior? | **No** | The added annotation is a Python comment block. Structural AST equality and exact original Git blob are checked in the preparation manifest. |

## Exact source baseline

- [Custom SRC-101 parser/updater](https://github.com/bitcoinuniverseio/btc_stamps/blob/8666d779d23caf418edb2c78262a0338b7314b7f/indexer/src/index_core/src101.py), Git blob `20ac95fa5466c5ac04e7b6b9d583475e862f308d`.
- [Custom block finalization](https://github.com/bitcoinuniverseio/btc_stamps/blob/8666d779d23caf418edb2c78262a0338b7314b7f/indexer/src/index_core/blocks.py), which inserts SRC-101 transaction records and calls `update_src101_owners` during finalization.
- [Official SRC-101 comparison](https://github.com/stampchain-io/btc_stamps/blob/8a7365bf951a66f3a5e25dc15e8702f65b5d23d8/indexer/src/index_core/src101.py), version 1.9.5, Git blob `2afa30140f3e8b2991229632852037561999bb1b`.

The complete recursive Git tree for the custom baseline was retrieved without truncation. It contains no `AGENTS.md`; therefore no repository or nearest-ancestor AGENTS instruction applies to the source file or this new docs directory. Workspace ancestors were also checked.

## Failure mechanism and impact

The unchanged token validator accepts scalar base64 strings and keeps `tokenid` as that string; it stores the decoded lowercase name as the scalar `tokenid_utf8`. Transfer processing reads existing ownership and expiry, validates the creator, and marks the transfer valid without changing either field into an array.

The custom `update_src101_owners` branch for `TRANSFER` with no earlier matching owner update iterates over the length of the encoded string and indexes both values. For `YWxpY2U=` and `alice`, those lengths are eight and five. The loop raises before reaching `update_owner_table`. The official compared function builds one row directly from both scalar values.

An isolated diagnostic reproduced that difference using the exact source functions. It used synthetic owner labels after the ownership/expiry gate and replaced only the SQL writer with a capture function. Token syntax validation ran with the actual base64 and excluded-character helpers. **It did not prove a live stuck block**: that operational effect requires the actual deployed version and full block transaction path. If this custom code is used, the reproduced exception makes valid standalone transfers a mainnet readiness blocker.

## Chosen repair

Modify only the scalar transfer persistence path needed to preserve the existing parser contract. A successful transfer must produce exactly one update for the full deployment hash and full scalar token ID, with the validated new owner, prior owner, unchanged expiry, and the existing transfer record/primary-name reset behavior. Never split an encoded ID or decoded name into characters.

Do not introduce array transfers, broaden accepted transaction schemas, change activation heights, change token normalization, or treat a failing transfer as successfully indexed. Do not perform a destructive ownership backfill. If previously processed data needs repair, first establish the deployed commit and affected block range, compare canonical history, and prepare a separate reviewable recovery plan. The referenced official function is a comparison for this repair, not permission for a broad upstream merge.

## Implementation sequence

1. Pin the deployed executable/source and database checkpoint, including Bitcoin network and block hash. Preserve this preparation baseline so the actual target delta can be reviewed.
2. Add a regression covering scalar token validation followed by the owner updater, then implement the one-row scalar update. Preserve exact token identity and transfer reset semantics.
3. Exercise raw transaction parsing into `parse_src101`, valid/invalid ownership and expiry, and the actual block finalization SQL transaction. Verify one correct owner row and transaction state commit atomically.
4. Exercise multiple operations for the same name within a block, a failed operation between valid operations, block rollback, and reorg replay. Compare all owner fields, not only counts or UI labels.
5. Run a native non-mainnet lifecycle with a proven Stamps network profile and source/version/checkpoint attestation. Neither this custom baseline nor official 1.9.5 declares a native Signet selector. A Testnet profile must be explicitly justified and identified; an address prefix is insufficient.
6. Only after those gates, verify the intended mainnet deployment revision and observe correctly indexed transfer outcomes. Broadcast acceptance alone is not protocol success.

## Acceptance and residual limits

Required outcomes: a standalone valid scalar transfer updates exactly one existing name; malformed input and non-owner/expired transfers do not change ownership; full encoded identity survives unchanged; repeated operations, SQL failures, and reorg replay leave the deterministic canonical owner state; every reported outcome retains native transaction and block identity.

Open prerequisites are the live revision, network service and API contract, full parser/SQL regression environment, and native lifecycle evidence. The preparation leaves all executable behavior unchanged. `ANNOTATION_INDEX.json` maps the only annotated source location; `SOURCE_REGISTER.json` records the immutable references and diagnostic boundaries.
