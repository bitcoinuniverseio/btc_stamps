# Support

Where to take a question, by what kind of question it is.

## Before asking

Most questions already have an answer in the repository:

- [`docs/README.md`](docs/README.md) is the documentation map.
- [`docs/CONSENSUS.md`](docs/CONSENSUS.md) answers "why did the indexer classify this
  transaction that way".
- [`indexer/.env.sample`](indexer/.env.sample) documents every environment variable, with
  defaults and inline explanations.
- [`ops/`](ops/) covers supervision, alerting, and deployment.

## Where to go

| Situation | Where |
| --- | --- |
| Security, consensus divergence, or supply-chain problem | **Do not open a public issue.** Follow [`SECURITY.md`](SECURITY.md). |
| Bug in the indexer | [Open an issue](https://github.com/bitcoinuniverseio/btc_stamps/issues/new/choose) using the indexer bug template. |
| A change that affects consensus or performance | Use the consensus/performance change issue template. |
| Protocol design question or a proposal | Open a Stamps Improvement Proposal. See [`docs/sips/AUTHORING.md`](docs/sips/AUTHORING.md). |
| Question about the public API rather than the indexer | The API and explorer live in [bitcoinuniverseio/stampchain.io](https://github.com/bitcoinuniverseio/stampchain.io). |
| General discussion, ecosystem questions | [Bitcoin Stamps Telegram](https://t.me/BitcoinStamps) |
| Exploring stamps and tokens | [stampchain.io](https://stampchain.io/) |
| Protocol reference site | [bitcoinstamps.xyz](https://bitcoinstamps.xyz) |

## Filing a good indexer issue

Consensus bugs are much easier to fix when the report is reproducible. Include:

- the **block height** and, if you have it, the **transaction hash**;
- what you expected the indexer to record and what it actually recorded;
- the value of `txlist_hash` and `ledger_hash` your instance produced for that block, and the
  values you are comparing against;
- your Python version, whether the Rust parser is enabled, and whether `FORCE` was set;
- whether the block was processed during initial sync, near the tip, or during a reparse.

A divergence report with a block height and both hashes is usually enough to locate the cause.
A report without a height rarely is.

## What is not supported here

- Investment, trading, or price questions.
- Help recovering funds or reversing a transaction. Bitcoin Stamps are immutable by design and
  no maintainer can undo an on-chain action.
- Requests to add, remove, or block a specific ticker. There is no reserved ticker list and no
  blocklist in the protocol, and maintainers cannot create one.

## Response expectations

This is community-maintained software provided without warranty. Issues are triaged on a best
effort basis. Security reports follow the timeline in [`SECURITY.md`](SECURITY.md).
