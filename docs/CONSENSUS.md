# Bitcoin Stamps consensus reference

This document describes the rules this indexer actually applies when it decides whether a
Bitcoin transaction is a Stamp, an SRC-20 operation, or an SRC-101 operation, and how it
derives the per-block hashes that other implementations reconcile against.

Every rule below is traced to a file and a symbol in `indexer/src/`. Where the code and an
older prose description disagreed, the code wins and this document follows the code.

> This is a description of an implementation, not a ratified standard. Bitcoin Stamps has no
> on-chain consensus mechanism: agreement is agreement between indexers. If you are writing a
> second implementation, this document plus the named source files are what you need to match.

## Contents

1. [Where the rules live](#where-the-rules-live)
2. [Activation heights](#activation-heights)
3. [Carriers](#carriers)
4. [Carrier precedence](#carrier-precedence)
5. [Stamp classification](#stamp-classification)
6. [Base64 determinism](#base64-determinism)
7. [SRC-20 rules](#src-20-rules)
8. [SRC-101 rules](#src-101-rules)
9. [Consensus hashes](#consensus-hashes)
10. [Reorganizations and rollback](#reorganizations-and-rollback)
11. [External ledger validation](#external-ledger-validation)
12. [What is not consensus](#what-is-not-consensus)

## Where the rules live

| Concern | File |
| --- | --- |
| Every activation height and network constant | `indexer/src/config.py` |
| Carrier decode (multisig, P2WSH, ARC4, prefix) | `indexer/src/index_core/transaction_utils.py` |
| Script shape checks (1-of-3 multisig, P2WSH, burn keys) | `indexer/src/index_core/script.py` |
| ARC4 keystream | `indexer/src/index_core/arc4.py` |
| Interpreter-independent base64 | `indexer/src/index_core/base64_utils.py` |
| Stamp classification, cursed and POSH rules | `indexer/src/index_core/models.py` |
| Base64 decode dispatch and repair era | `indexer/src/index_core/stamp.py` |
| SRC-20 parsing and validation | `indexer/src/index_core/src20.py` |
| SRC-721 composition | `indexer/src/index_core/src721.py` |
| SRC-101 parsing and validation | `indexer/src/index_core/src101.py` |
| Per-block hashes and checkpoints | `indexer/src/index_core/check.py`, `indexer/src/index_core/block_validation.py` |
| Reorg detection, rollback, chain integrity | `indexer/src/index_core/blocks.py` |

## Activation heights

Every boundary is a named constant. Read the constant, never a literal.

| Constant | Mainnet height | Effect |
| --- | --- | --- |
| `CP_STAMP_GENESIS_BLOCK` | 779652 | First valid Classic Stamp, via Counterparty. Also `BLOCK_FIRST_MAINNET`. |
| `CP_SRC20_GENESIS_BLOCK` | 788041 | First SRC-20, via Counterparty. Also the `ledger_hash` chain origin. |
| `CP_SRC721_GENESIS_BLOCK` | 792370 | SRC-721 recognised from this height. |
| `BTC_SRC20_GENESIS_BLOCK` | 793068 | First SRC-20 carried directly in a Bitcoin transaction. |
| `STOP_BASE64_REPAIR` | 784550 | At or below this height a padding repair pass runs before base64 decode. Above it, no repair. |
| `CP_SRC20_END_BLOCK` | 796000 | Counterparty-carried SRC-20 is ignored at and above this height. Classic Stamp images via Counterparty stay supported at every height. |
| `STRIP_WHITESPACE` | 797200 | Above this height, leading whitespace is stripped from decoded payload bytes before MIME detection. |
| `CP_BMN_FEAT_BLOCK_START` | 815130 | Audio file support for BMN. |
| `CP_P2WSH_FEAT_BLOCK_START` | 833000 | Two effects: Classic Stamps may use P2WSH, and SRC-20 numeric fields stop being character-stripped (see [Numeric parsing eras](#numeric-parsing-eras)). |
| `BTC_SRC20_OLGA_BLOCK` | 865000 | P2WSH data chunks are collected from transaction outputs. This gate is protocol-agnostic in the decoder: it enables the P2WSH carrier for SRC-20 and for SRC-101 alike. |
| `CP_SUBASSET_FEAT_BLOCK_START` | 866000 | Counterparty subassets no longer require XCP, so they stop being forced to cursed and POSH. |
| `BTC_SRC101_GENESIS_BLOCK` | 870652 | SRC-101 recognised from this height. |
| `BTC_SRC101_IMG_OPTIONAL_BLOCK` | 872200 | SRC-101 mint drops the required `img` key and relaxes from exact key match to superset match. |
| `BTC_SRC101_OLGA_BLOCK` | 940000 | On the P2WSH branch, the destination output value is carried into `destination_nvalue`. It does **not** gate P2WSH chunk collection. |
| `SVG_GZIP_DETECTION_V2` | 999999 | Not yet reached. Placeholder for a future SVG gzip detection change. |
| `ENHANCED_MIME_DETECTION` | 999999 | Not yet reached. Placeholder for a future MIME detection change. |

Two corrections that repeatedly trip up reimplementations:

- **OLGA is not one height.** Classic Stamps at 833000, SRC-20 at 865000. There is no third
  OLGA activation for SRC-101: SRC-101 rides the same P2WSH collection gate at 865000.
  `BTC_SRC101_OLGA_BLOCK` (940000) only decides whether `ctx.vout[0].nValue` is recorded as the
  SRC-101 destination value on that branch. See `process_vout` and `get_tx_info` in
  `transaction_utils.py`.
- **Only SRC-20 stops at 796000.** Classic stamp images issued through Counterparty are still
  indexed above that height.

## Carriers

Three carriers exist. A fourth output type, `OP_RETURN`, is never a carrier.

### Bare multisig

The original format. `script.get_checkmultisig` accepts a strictly narrow shape.

```
OP_1 <pubkey_a> <pubkey_b> <burn_pubkey> OP_3 OP_CHECKMULTISIG
```

- The ASM must have exactly 6 elements, `asm[0] == 1`, `asm[4] == 3`, and
  `asm[5] == "OP_CHECKMULTISIG"`. It is 1-of-3 and nothing else. A 1-of-2 or a 2-of-3 is
  rejected, unlike Counterparty's own decoder (which is kept commented out in `script.py` for
  comparison).
- Data lives in pubkeys 1 and 2 only, `asm[1:3]`. The third pubkey is not data.
- Each data pubkey contributes `pubkey[1:-1]`: the first and last byte are stripped, then the
  remainders are concatenated.
- `asm[3]`, the third pubkey, must hex-match an entry in `config.BURNKEYS` for `keyburn` to be
  set to 1. There are five accepted burn keys, all repeating-byte patterns.
- The concatenated chunk is decrypted with ARC4. The key is the first input's previous
  transaction hash, byte-reversed: `arc4.init_arc4(ctx.vin[0].prevout.hash[::-1])`.
- The decrypted chunk carries a 2-byte big-endian length prefix. `stamp:` must appear at
  offset 2, immediately after the prefix. If `len(chunk) < 2 + length`, decode raises.
- Payload is `chunk[2 + len("stamp:") : 2 + length]`.
- Destination is decoded from `ctx.vout[0].scriptPubKey`.

Reference: `decode_checkmultisig` in `transaction_utils.py`.

### OLGA over P2WSH

Active for P2WSH chunk collection from block 865000 (`BTC_SRC20_OLGA_BLOCK`).

- Every output whose script is `OP_0 <32 bytes>` **at index greater than 0** contributes its
  32 bytes. Output 0 is the recipient, not data.
- Chunks are concatenated in output order, then trailing `\x00` padding is stripped.
- There is no ARC4 on this path.
- The concatenated data carries the same 2-byte big-endian length prefix, but `stamp:` sits at
  **offset 0 of the data chunk** (that is, at offset 2 of the framed buffer), not at offset 2
  of the chunk as in multisig framing. Concretely: `data_chunk = buf[2 : 2 + length]` and the
  test is `data_chunk.startswith(b"stamp:")`.
- `keyburn` is forced to 1 on this path. The comment in the source is explicit that this
  substitutes for the multisig burn-key requirement.
- Destination is decoded from `ctx.vout[0].scriptPubKey`. From block 940000
  (`BTC_SRC101_OLGA_BLOCK`), `ctx.vout[0].nValue` is also recorded as the destination value.

Reference: `process_vout` and the P2WSH branch of `get_tx_info` in `transaction_utils.py`.

### Counterparty

Classic Stamps and early SRC-20 arrive as Counterparty issuances, fetched from a Counterparty
node rather than decoded from raw script. The stamp payload is base64 inside the asset
description, located by a case-insensitive search for `stamp:` and split on the first `;` into
mimetype and base64. See `parse_base64_from_description` in `base64_utils.py`.

Counterparty-carried SRC-20 is honored only below `CP_SRC20_END_BLOCK` (796000), and only when
the CPID starts with `A` and asset supply is 0. Classic stamp images via Counterparty have no
end height.

### OP_RETURN

`OP_RETURN` is never an SRC-20 or SRC-101 carrier. For Counterparty-sourced stamps it is a
disqualifier: a transaction flagged `is_op_return` cannot become `is_btc_stamp` and is routed
to the cursed path instead (`process_all_stamps` and `process_cursed_with_other_conditions` in
`models.py`). The one exception is the P2WSH path, which resets the flag to `None` after
decode because OLGA transactions commonly also carry an `OP_RETURN`.

## Carrier precedence

In a transaction that contains both P2WSH data chunks and a qualifying bare multisig, **P2WSH
wins unconditionally**. The multisig branch in `get_tx_info` is an `elif`, so once any P2WSH
chunk has been collected the multisig branch is never attempted, even when the P2WSH data
subsequently fails its length or prefix check and yields nothing.

This is not a bug and must be reproduced exactly. It matches the stampscan reference
implementation. Adding a multisig fallback would change which transactions are stamps and
therefore fork `txlist_hash`. Tracked as issue #749, resolved WONTFIX. The exclusion is
documented in a comment at the branch itself.

## Stamp classification

Once a payload is decoded, `models.py` decides three flags: `is_btc_stamp`, `is_cursed`, and
`is_posh`.

A Counterparty-sourced item becomes a valid stamp when all of the following hold:

- the detected `ident` is not `UNKNOWN`;
- `asset_longname` is unset, or is set and the height is at or above
  `CP_SUBASSET_FEAT_BLOCK_START` (866000);
- the CPID starts with `A`;
- `is_op_return` is falsy;
- the file suffix is not in `INVALID_BTC_STAMP_SUFFIX`, which is
  `["plain", "octet-stream", "js", "css", "x-empty", "json"]`.

Otherwise it goes cursed. A CPID that does not start with `A` and whose suffix is not in that
invalid list is additionally marked POSH. Below block 866000, any subasset is forced to cursed
and POSH because subassets required XCP at the time.

Protocol gates on top of that:

- **SRC-20** requires `ident == "SRC-20"` and `keyburn == 1`. Either the transaction has no
  CPID (direct Bitcoin), or it has a CPID and is below 796000 with supply 0 and a CPID starting
  with `A`.
- **SRC-721** requires height at or above 792370, `keyburn == 1` or a P2WSH payload at or above
  833000, and supply at most 1.
- **SRC-101** requires height at or above 870652, `ident == "SRC-101"`, and `keyburn == 1`.

## Base64 determinism

`indexer/src/index_core/base64_utils.py` is consensus-critical and exists for one reason.

CPython 3.13 tightened `binascii.a2b_base64` so that it rejects loosely formed base64 that
3.10 through 3.12 decoded leniently: embedded `=` padding, stray non-alphabet characters, and
inputs whose data-character count is one more than a multiple of 4. A real stamp payload at
**block 783775** contains embedded padding. On 3.10 through 3.12 it decoded to a 373-byte PNG.
On 3.13 it raised, the stamp was misclassified, and `txlist_hash` forked. Tracked as issue #871.

The fix is `lenient_b64decode`, a version-independent reimplementation of the 3.10 non-strict
decoder. All stamp base64 decoding routes through it, so the result is identical on every
interpreter with no per-version branching and no monkey-patching. It is checked against an
85k-input fuzz corpus and the real block-783775 payload in
`indexer/tests/test_python313_base64_regression.py`.

**Practical consequence for operators: run Python 3.10, 3.11, or 3.12.** The decoder removes
the known stdlib divergence, but the project only consensus-validates 3.10 through 3.12: the
`reparse-validate.yml` matrix covers exactly those three. Python 3.13 is in the unit-test matrix
in `python-check.yml` so the code must still import and pass unit tests there, and that green
run is explicitly **not** a statement of consensus support. A separate
`python313-consensus-gate` job asserts as a strict xfail that stdlib `b64decode` on 3.13 still
rejects the block-783775 payload; it turns red if 3.13 behaviour ever changes, which is the
signal to revisit #871.

Two more height-dependent base64 rules:

- At or below `STOP_BASE64_REPAIR` (784550), a repair pass runs (`decode_base64_with_repair`).
  Above it, no repair.
- At or above `CP_P2WSH_FEAT_BLOCK_START` (833000), the base64 string is validity-checked
  before decoding and an invalid string excludes the transaction outright.

## SRC-20 rules

### Pipeline

1. `quick_filter_src20_transaction` (`transaction_utils.py`) is a cheap pre-filter mirroring
   the Rust parser: include the transaction if it has a P2WSH pattern with data containing the
   prefix, or a burn-keyed multisig whose ARC4-decrypted chunk carries the prefix at offset 2.
2. `check_format` (`src20.py`) is the inclusion gate. Returning `None` means the transaction is
   not an SRC-20 stamp at all. This decision affects stamp numbering.
3. `Src20Validator.process_values` normalizes fields and records format errors.
4. `Src20Processor.validate_and_process_operation` applies the state rules.

### JSON parsing

- Parsed with a custom `parse_float` that **rejects any value containing `e` or `E`**.
  Scientific notation excludes the transaction. Integers are parsed straight to `Decimal`.
- Any JSON decode error, type error, or the scientific-notation `ValueError` excludes the
  transaction.

### Ticker rules

- Compared after `convert_to_utf8_string`, then lowercased and escaped by the validator.
- **Maximum 5 Unicode code points.** The check is `len(tick_value) > 5` on a Python string, so
  it counts code points, not bytes and not grapheme clusters. Five emoji is a valid ticker.
- Every code point must be in `TICK_PATTERN_SET`, the union of two allowlists in `config.py`:
  - `SUPPORTED_CHARS`, **79 ASCII characters**: `.!#$%&()*0123456789<=>?@A-Z^_a-z~`
  - `SUPPORTED_UNICODE`, **1154 distinct emoji code points** (1155 entries with one duplicate,
    U+1F642). The union is **1233 accepted code points**.
- Note what is absent: no `-`, no space, no `+`, no `,`, no `"`, no `'`, no `[`, no `]`,
  no `{`, no `}`, no `/`, no `\`, no `:`, no `;`, no backtick.
- **There are no reserved tickers and no blocklist.** Any ticker matching the pattern can be
  deployed, first deploy wins.
- `tick_hash` is `sha3_256` (NIST SHA3, not Keccak) of the lowercased ticker.

### Numeric parsing eras

`max`, `lim`, and `amt` are read differently either side of block 833000
(`CP_P2WSH_FEAT_BLOCK_START`).

| Height | String value handling |
| --- | --- |
| below 833000 | Every character that is not a digit and not `.` is **stripped**, then the remainder is parsed. |
| 833000 and above | The string is parsed as-is. A malformed string excludes the transaction. |

The old behaviour is silently lossy and is the source of several historically odd balances:

| Input string | Below 833000 reads as | 833000 and above |
| --- | --- | --- |
| `"1,000"` | `1000` | excluded, invalid decimal |
| `"-5"` | `5` | excluded, invalid decimal |
| `"1 000"` | `1000` | excluded, invalid decimal |
| `"12abc"` | `12` | excluded, invalid decimal |

After parsing, every checked value must satisfy `0 <= value <= 2**64 - 1` and must not be NaN,
at every height.

### Field normalization

- `max` and `lim` are quantized to an integer with `ROUND_DOWN`. `1000.9` deploys as `1000`.
- `amt` is not quantized. Its decimal place count must not exceed the deploy's `dec`, otherwise
  the operation is invalidated with status `ID`.
- `dec` must match `^[0-9]+$` and be between 0 and 18 inclusive. An absent `dec` on a deploy
  defaults to 18.
- `p`, `op`, and `holders_of` are uppercased. `tick` is lowercased.
- An empty-string field becomes `None`.

### Operations

Required key sets in `check_format` are **subset** tests (`input_keys >= key_set`), so extra
keys are tolerated:

| Operation | Required keys | Range-checked values |
| --- | --- | --- |
| `DEPLOY` | `op`, `tick`, `max`, `lim` | `max`, `lim` |
| `MINT` | `op`, `tick`, `amt` | `amt` |
| `TRANSFER` | `op`, `tick`, `amt` | `amt` |

`validate_and_process_operation` dispatches only `DEPLOY`, `MINT`, and `TRANSFER`. Anything
else, including a `BULK_XFER` payload, gets status `UO: UNSUPPORTED OP` and is invalid.
`Src20Processor.handle_bulk_transfer` exists in the source but no dispatcher path reaches it,
so bulk transfer is **not a live operation** despite the code being present.

Deploy accepts the first deploy of a ticker only. A second deploy gets `DE`. There is no check
that `lim <= max` at deploy time; the relationship is enforced at mint time instead, where the
effective per-mint limit is `min(lim, max)`.

### The clamping rule

This is the single most commonly mis-specified rule in the protocol. Read the `is_invalid`
column carefully.

| Status | Message | Invalid? | Meaning |
| --- | --- | --- | --- |
| `DE` | `INVALID DEPLOY: {tick} DEPLOY EXISTS` | yes | Ticker already deployed. |
| `ND` | `INVALID {op}: {tick} NO DEPLOY` | yes | Mint or transfer before deploy. |
| `OM` | `OVER MINT {tick} {total_minted} >= {deploy_max}` | yes | Supply already exhausted. |
| `NA` | `INVALID AMT {op} {tick}` | yes | Missing or falsy `amt` on mint or transfer. |
| `OMA` | `REDUCED AMT {tick} FROM: {x} TO: {y}` | **no** | Mint would exceed remaining supply. Amount is **reduced to the remainder** and the mint stays **valid**. |
| `ODL` | `REDUCED AMT {tick} FROM: {x} TO: {y}` | **no** | Mint exceeds the per-mint limit. Amount is **reduced to the limit** and the mint stays **valid**. |
| `BB` | `INVALID XFR {tick} - total_balance {b} < xfer amt {a}` | yes | Insufficient balance. Transfers are **not** clamped. |
| `UO` | `UNSUPPORTED OP {op}` | yes | Operation not dispatched. |
| `ID` | `INVALID DECIMAL {tick} - decimal len {n} > {dec}` | yes | Too many decimal places for the deploy's `dec`. |

Mint evaluation order in `handle_mint`:

1. `deploy_lim = min(lim, max)` when both are set, otherwise 0.
2. If `total_minted >= max`, emit `OM` and stop. The mint is invalid.
3. If `amt > (max - total_minted)`, emit `OMA` and set `amt = max - total_minted`.
4. If `amt > deploy_lim`, emit `ODL` and set `amt = deploy_lim`.
5. Credit the (possibly reduced) `amt`.

So a mint of 1,000,000 against a token with `lim` 1000 and 400 left in supply produces a valid
mint of 400, carrying both an `OMA` and an `ODL` status message. An implementation that rejects
it instead will diverge on balances and on `ledger_hash`.

Transfers behave differently: an over-balance transfer is rejected outright with `BB`, never
partially filled.

## SRC-101 rules

SRC-101 is the Bitcoin-native naming protocol, gated from block 870652.

### Operations

The live operations are `DEPLOY`, `MINT`, `TRANSFER`, `SETRECORD`, and `RENEW`. There is no
`reg` operation.

`check_src101_inputs` enforces key sets by **symmetric difference**, which means an exact key
match with no extra and no missing keys, except for mint at or above block 872200.

| Operation | Required keys | Match |
| --- | --- | --- |
| `deploy` | `p`, `root`, `op`, `name`, `lim`, `owner`, `rec`, `tick`, `pri`, `desc`, `mintstart`, `mintend`, `wla`, `imglp`, `imgf`, `idua` | exact |
| `transfer` | `p`, `op`, `hash`, `toaddress`, `tokenid` | exact |
| `mint` below 872200 | `p`, `op`, `hash`, `toaddress`, `tokenid`, `dua`, `prim`, `sig`, `img`, `coef` | exact |
| `mint` at or above 872200 | same minus `img` | superset |
| `setrecord` | `p`, `op`, `hash`, `tokenid`, `type`, `data`, `prim` | exact |
| `renew` | `p`, `op`, `hash`, `tokenid`, `dua` | exact |

Any other `op` value returns `None` and the transaction is not an SRC-101 operation.

### Signatures

Two different cryptographic checks exist and they are not interchangeable.

- **Mint price coefficient.** When a mint carries a non-empty `sig`, the indexer verifies it
  with `cryptography`'s ECDSA over SECP256K1 and SHA-256, against the **deploy's `wla`
  compressed public key**. The signed message is `json.dumps` of a dict containing `hash`,
  `coef`, `address`, `tokenid`, and `dua`; if that fails, a second attempt drops `tokenid`.
  A valid signature sets the price coefficient; an invalid one yields status `IRS` and the mint
  is rejected. `eth_account` is not involved here.
- **Setrecord Ethereum binding.** `check_and_convert_addres_type_data` uses
  `eth_account.Account.recover_message` with `encode_defunct` over the hex previous transaction
  hash. This **recovers a signer address** from the supplied signature and then validates that
  the recovered address is a well-formed Ethereum address. It is an address-derivation step for
  the record being set, not a verification of the mint signature.

### Address validation

`ADDRESS_REGEX` and `ETH_ADDRESS_REGEX` are declared at the top of `src101.py` and are **never
referenced anywhere**. Do not reimplement them as if they were rules. Real Bitcoin address
checks go through `check_valid_bitcoin_address` in `index_core/util.py`; the Ethereum side uses
`check_valid_eth_address` on the recovered address.

## Consensus hashes

Three hashes are stored per block in the `blocks` table. Two of them are chained and verified;
one is not.

| Field | Content hashed | Chained | Verified against stored value |
| --- | --- | --- | --- |
| `txlist_hash` | `str()` of the block's valid stamps, sorted by `stamp_number` | yes | yes |
| `ledger_hash` | `str()` of the block's processed SRC-20 operations | yes | yes |
| `messages_hash` | `str()` of the block's transaction hash list | yes | no |

Reference: `create_check_hashes` in `block_validation.py` and `consensus_hash` in `check.py`.

### txlist_hash and messages_hash

```
new = dhash_string(previous_hash + f"{version}{content}")
```

where `dhash_string` is hex of `sha256(sha256(bytes))` and `version` is
`CONSENSUS_HASH_VERSION_MAINNET = 1` (testnet 7, regtest 1). The chain is seeded at
`BLOCK_FIRST` with `dhash_string(CONSENSUS_HASH_SEED)`, where the seed is the fixed sentence
stored in `check.py`.

### ledger_hash

`ledger_hash` uses a different construction. It is a **single** SHA-256, not a double hash:

```
new = shash_string(previous_hash.encode("utf-8") + content.encode("utf-8"))
```

with no version byte in the input. Three special cases:

- Blocks with no SRC-20 activity produce the **empty string**, not a hash. The chain skips them:
  the previous hash is the most recent non-empty `ledger_hash` in the table, not the immediately
  preceding block.
- At exactly `CP_SRC20_GENESIS_BLOCK` (788041) the value is the hard-coded constant
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- At block 788042 the previous hash is initialized to `shash_string("")`.

### Verification and checkpoints

When a value already exists in the row, the recalculated value must match it, except for
`messages_hash`. A mismatch goes through `handle_consensus_error`, which halts unless `FORCE` is
set. `MAX_CONSENSUS_RETRIES` (default 3) bounds retries.

`CHECKPOINTS_MAINNET` in `check.py` pins expected `txlist_hash` and `ledger_hash` values at
selected heights. A calculated value that disagrees with a checkpoint raises a consensus error.
Checkpoints are the fastest way for a new implementation to find where it diverged.

## Reorganizations and rollback

The indexer processes confirmed blocks only. **There is no mempool handling anywhere in the
codebase.** Nothing is indexed before it is in a block, so there is no unconfirmed state to
invalidate.

### Detection

Three independent detectors:

1. **Orphan parent check**, on every block. The stored `block_hash` of `block_index - 1` is
   compared with the parent hash reported by bitcoind. On mismatch the loop walks backwards
   until the stored hash and the backend parent agree, then rolls back.
2. **Duplicate block insert.** A primary key collision on insert is treated as a reorg
   signature and triggers rollback.
3. **Startup chain integrity check** (`verify_recent_chain_integrity`). On every start, the last
   `STARTUP_CHAIN_INTEGRITY_DEPTH` stored block hashes (default 100, set 0 to disable) are
   compared against `getblockhash` from oldest to newest. The **oldest** mismatch is returned
   and the indexer rolls back to that height minus 1. Returning the oldest matters: if a reorg
   replaced blocks N through N+k, all of them mismatch and all must be refetched.
   This is defense in depth for the case where the indexer crashes mid-reorg and restarts after
   the tip has already moved past the orphan-check window. It exists because that happened at
   block 945189 on 2026-04-15 (issue #779). The check never raises: a bitcoind error makes it
   inconclusive and the indexer still starts.

### Rollback depth

`calculate_rollback_depth` chooses depth by reason:

| Reason contains | Blocks rolled back |
| --- | --- |
| `Chain reorganization` | 10 |
| `Duplicate key` or `transient` | 1 |
| anything else | 3 |

### Rollback sequence

1. Record the target in the stuck-rollback detector, which pages operations if the same target
   recurs 3 times in 30 minutes.
2. Invalidate the block count cache.
3. Verify the Counterparty node has also rolled back past the target. If it has not,
   `find_common_ancestor_with_xcp` walks back until both Bitcoin and Counterparty agree.
4. `purge_block_db(db, target_block)` deletes rows at and above the target.
5. `rebuild_balances(db)` and `rebuild_owners(db)` recompute derived state.
6. Notify the API webhook to invalidate caches, if configured. A webhook failure does not fail
   the rollback.
7. Reset the Counterparty pipeline and wait 60 seconds for Counterparty to catch up.

A failure inside step 4 through 6 exits the process unless `FORCE` is set. Repeated rollback to
the same height trips `check_rollback_loop` and terminates rather than looping forever.

## External ledger validation

After computing `ledger_hash`, the indexer can compare it against an external reference. This
is a **check**, not an input: it never changes what the indexer records.

- `SRC_VALIDATION_API1` is a public OKX reconciliation endpoint.
- `SRC_VALIDATION_API2` is a stampscan endpoint that requires a secret supplied through the
  `SRC_VALIDATION_SECRET_API2` environment variable. The value is operator-held and is not in
  this repository.
- When validation is unavailable, blocks may be processed with `FORCE=True`. Setting
  `ENABLE_SRC20_BACKGROUND_VALIDATION=true` (the default) queues those blocks for revalidation
  once the endpoint returns.
- On a mismatch, `compare_balances` and `print_balance_differences` report per-ticker and
  per-address deltas so the divergence can be located.

## What is not consensus

These are real behaviours of this software that a second implementation does not need to copy:

- Rendered SVG output for SRC-20 operations (`build_src20_svg_string`). Presentation only.
- Market data, sales history, holder counts, collection aggregation. All derived and rebuildable.
- Media storage, S3, CloudFront, Universe media ingestion.
- Caching layers, connection pooling, batch sizes, memory thresholds.
- The Rust parser. It is a performance path only; the pure-Python path must produce identical
  results and is used whenever `DISABLE_RUST_PARSER` is set or the extension is unavailable.
- Alerting, supervision, webhooks.

If a change touches anything in the [Where the rules live](#where-the-rules-live) table, treat
it as consensus-affecting and run the reparse validation described in
[`indexer/docs/reparse.md`](../indexer/docs/reparse.md) before merging.

## See also

- [PROTOCOLS.md](./PROTOCOLS.md) for message formats and examples.
- [ARCHITECTURE.md](./ARCHITECTURE.md) for the component map.
- [DATABASE.md](./DATABASE.md) for the schema these rules write into.
- [`indexer/docs/reparse.md`](../indexer/docs/reparse.md) for replaying and validating history.
- [`indexer/docs/block-processing-architecture.md`](../indexer/docs/block-processing-architecture.md)
  for the block pipeline in detail.
