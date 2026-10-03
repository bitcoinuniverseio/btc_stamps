# SRC-101 record, renewal and parser build contract

Scope: bitcoinuniverseio/btc_stamps isolated implementation based on de1aecbedb6decb9aff521669f739c6c85b0d2bc (custom main8666d779d23caf418edb2c78262a0338b7314b7f). Production deployment remains unobserved/unchanged. Native parser/MySQL fixtures exercise actual Python parser, block finalization and rebuild, with synthetic chain rows. They do not establish public-network transaction or wallet acceptance.

## SQL history and projection

SRC101 contains all parsed operations; SRC101Valid contains accepted operations. Read a completed `blocks.indexed=1` snapshot and independently verify transaction block and checkpoint against the owned Bitcoin node. Use ordered `(block_index,tx_index)` history. `node_version_history` is parser metadata, not chain identity.

TRANSFER, RENEW and SETRECORD carry a scalar tokenid; MINT carries a list. The scalar validator preserves its base64 bytes and decodes/lowercases its UTF-8 name; MINT normalizes list names and re-encodes them. Do not coerce scalar transfer identities into arrays. Native accepted names and canonical token identity must both be bound.

SETRECORD's `address_btc`, `address_eth`, `txt_data` columns persist the resulting merged record projection. `prim` is boolean. `txt_data` is JSON serialization when truthy and SQL NULL otherwise. Raw `type` and `data` are not persisted; decode the actual final transaction to bind its original operation. RENEW retains merged records and primary state. TRANSFER clears addresses/TXT/primary, preserving the image. Every accepted event must be applied in transaction order, including other names in the same deployment. A true primary clears all current rows sharing the same non-NULL `(deploy_hash,address_btc)`; a single-token replay is insufficient. MINT resets records, starts expiry and replaces image; expired remint retains the previous owner and stable owner row identity/index.

`SRC101.mint_img` and `SRC101Valid.mint_img` are new nullable JSON columns holding the exact parsed MINT image array. `[null]` proves an image slot was NULL. SQL NULL is missing historical evidence, and rebuild refuses it until actual-chain reparse. Legacy `img` is not used as proof because the old writer omitted it and semicolon serialization is ambiguous. `owners.img` widens from255 to4096 characters with binary collation. Rebuild compares image, owner identity/index, ownership, expiry and records. Rebuild deletion uses transactional DELETE, so insertion failure rolls back; no TRUNCATE implicit commit. Historical SETRECORD rows with all three record fields NULL likewise block destructive rebuild.

## Renewal and final transaction

Pinned native `Src101Processor.handle_renew` requires current creator ownership and **block_timestamp < expire_timestamp**. The seemingly permissive max-expiry branch in `update_valid_src101_list` is downstream of this rejection. Native tests reject both equality and expiry+99. No expired renewal acceptance is claimed.

`dua` and deployment `idua` must be positive integers. Parsed duration is `ceil(dua/idua)*idua` years; each year is31536000 seconds. Renewal selects price by Python `len(tokenid_utf8)` (Unicode code points after lowercasing), or key0 if that length is absent. Missing price or price=-1 rejects. Required satoshis are selected integer price multiplied by normalized duration/idua. Native code currently uses Python division for this integer ratio; app exact arithmetic must fail closed on unsupported native rounding rather than silently assuming different semantics.

Native deployment lookup reads accepted DEPLOY by `tx_hash` and p='SRC-101': lim, pri, mintstart, mintend, wla, imglp, imgf, idua. Recipients come from `recipients(deploy_hash,address,block_index)` and prices from `src101price(deploy_hash,len INT,price BIGINT signed,block_index)`. Proof readers must bind these projections to the accepted deployment and active checkpoint, not trust cached helper output.

For bare MULTISIG, pinned `transaction_utils.decode_checkmultisig` derives destination/value from **vout0 only**. It does not sum matching outputs. ARC4 uses the first input's previous txid. The renewal handler compares this destination_nvalue with rent; unlike MINT, it contains no destination-in-rec check. The application should separately bind its chosen published recipient and exact rent in the reviewed payment intent; do not invent an extra consensus rule.

## SETRECORD wire behavior

Exact keys are p,op,hash,tokenid,type,data,prim. The parser maps type/data to `<type>_data`; supported effects come from address or txt. `prim` wire value is the string 'true' or 'false'. A valid operation needs a nonempty address or TXT update. Address fields absent from an update retain prior values. Truthy TXT replaces the previous TXT object/value; it is not a deep merge. An address update with prim=true must have btc equal to creator. A TXT-only prim=true operation is handled by the native current-address selection rule; no stronger raw rule is invented.

BTC address values use the native address validator. ETH data is a signature of the first input previous txid hex, recovered via Ethereum signed-message semantics; persisted ETH is the recovered address without0x. It is not a raw arbitrary Ethereum address string. Ownership, expiry, native current records and independently decoded final payload all remain necessary.

## Source metadata

The parser writes component_name='stamps_indexer' in node_version_history; extra_info is:

```
{schema:'stamps-parser-source-v1', build_id:string|null,
 source_digest_sha256:hex, source_files:{'indexer/src/<file.py>':sha256},
 effective_protocol:{activations:{CONFIG_BLOCK_CONSTANT:integer},
   testnet:config.TESTNET, regtest:config.REGTEST,
   network_profile:STAMPS_NETWORK|null,
   signet_challenge:STAMPS_SIGNET_CHALLENGE|null}}
```

All actual Python files beneath indexer/src are hashed. Source map SHA256 hashes recursively sorted compact JSON encoded UTF8 (`json.dumps(sort_keys=True,separators=(',',':'),ensure_ascii=True)`). Use the same serialization for the approved effective protocol profile hash. Activation entries include integer uppercase config names ending `_BLOCK`, `_BLOCK_START`, `_BLOCK_END`, excluding booleans. A build ID is explicit operator input STAMPS_APPROVED_BUILD_ID, syntax-limited; the parser never declares it approved or infers a commit from1.9.3. Metadata changes supersede the current row even when semantic version is unchanged.

The application must match separately approved build ID, actual source digest and effective profile digest. The metadata network label/challenge records configuration; Bitcoin Core's exact chain/genesis/challenge and active checkpoint establish chain identity. Hashes cover Python source, not external native binaries or packages, which need their own release provenance.

## Composer pin

bitcoinuniverseio/stampchain.io@edcb253515cb3a118785de625e652cbfc079e8c6. `server/services/src101/transactionService.ts` prepareTransfer emits scalar tokenid. `operations/src101Operations.ts` serializes it. `utilityService.ts` blob13a83e99e3aed59647155ae2280bd67dddf7aa78 validates transfer without mutating identity. Its renewal composition does not itself establish native rent payment or accepted current state; bind and validate final transaction bytes independently.
