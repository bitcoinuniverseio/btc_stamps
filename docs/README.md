# Documentation map

Everything written down about this indexer, grouped by what you are trying to do. Paths are
relative to the repository root.

## Start here

| I want to | Read |
| --- | --- |
| Understand what this software is and run it | [`README.md`](../README.md) |
| Know exactly what makes a transaction a stamp | [`docs/CONSENSUS.md`](./CONSENSUS.md) |
| See the component map and data flow | [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) |
| Look up a message format | [`docs/PROTOCOLS.md`](./PROTOCOLS.md) |
| Understand the tables | [`docs/DATABASE.md`](./DATABASE.md) |
| Set up a development environment | [`docs/DEVELOPMENT.md`](./DEVELOPMENT.md) |
| Operate a production node | [`ops/`](../ops/) |
| Report a security issue | [`SECURITY.md`](../SECURITY.md) |
| Get help | [`SUPPORT.md`](../SUPPORT.md) |
| Contribute a change | [`CONTRIBUTING.md`](../CONTRIBUTING.md) |

## Protocol and consensus

| Document | Covers |
| --- | --- |
| [`docs/CONSENSUS.md`](./CONSENSUS.md) | Activation heights, carrier formats byte by byte, carrier precedence, stamp classification, SRC-20 and SRC-101 validation, the block hash model, reorg and rollback. The reference for anyone writing a second implementation. |
| [`docs/PROTOCOLS.md`](./PROTOCOLS.md) | Message shapes and worked examples for Classic Stamps, SRC-20, SRC-721, SRC-721r, SRC-101, and OLGA. |
| [`docs/whitepaper/`](./whitepaper/) | Protocol history, the UTXO permanence argument, economics, security model, and future direction. Start at [`index.md`](./whitepaper/index.md). |
| [`docs/sips/`](./sips/) | Stamps Improvement Proposals. [`AUTHORING.md`](./sips/AUTHORING.md) is the process; [`SIP-0110/`](./sips/SIP-0110/) is the one with a written specification, reference implementation, and test vectors. |
| [`docs/SRC20_UTXO_Binding_Transfer_Format_v2.0_Implementation_Guide.md`](./SRC20_UTXO_Binding_Transfer_Format_v2.0_Implementation_Guide.md) | Implementation guide for SIP-0002, which is superseded by SIP-0001. Historical. |

## Architecture and internals

| Document | Covers |
| --- | --- |
| [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) | Components, interfaces, data flow, error handling philosophy. |
| [`indexer/docs/block-processing-architecture.md`](../indexer/docs/block-processing-architecture.md) | The block pipeline in depth. |
| [`indexer/docs/rust-python-parser-issues.md`](../indexer/docs/rust-python-parser-issues.md) | Where the Rust and Python parser paths have differed and how parity is enforced. |
| [`indexer/docs/BACKGROUND_PROCESSING_CURRENT_STATE.md`](../indexer/docs/BACKGROUND_PROCESSING_CURRENT_STATE.md) | Background workers and what each one owns. |
| [`indexer/docs/async_upload.md`](../indexer/docs/async_upload.md) | Asynchronous media upload path. |
| [`indexer/docs/src721-recursive-implementation-summary.md`](../indexer/docs/src721-recursive-implementation-summary.md) | Recursive SRC-721 handling. |
| [`indexer/docs/src721-recursive-cursed-behavior.md`](../indexer/docs/src721-recursive-cursed-behavior.md) | Why some recursive SRC-721 items end up cursed. |
| [`docs/dev/CONSENSUS_SERIALIZER_HANDOFF.md`](./dev/CONSENSUS_SERIALIZER_HANDOFF.md) | Notes on the consensus serializer work. |

## Database and data

| Document | Covers |
| --- | --- |
| [`docs/DATABASE.md`](./DATABASE.md) | Schema overview and table responsibilities. |
| [`indexer/table_schema.sql`](../indexer/table_schema.sql) | The DDL itself. |
| [`docs/MARKET_DATA_CACHE_TABLES.md`](./MARKET_DATA_CACHE_TABLES.md) | Market data cache table definitions. |
| [`docs/MULTI_SOURCE_MARKET_DATA_CACHE_IMPLEMENTATION.md`](./MULTI_SOURCE_MARKET_DATA_CACHE_IMPLEMENTATION.md) | How multiple market data sources are reconciled. |
| [`indexer/docs/stamp-sales-history-implementation.md`](../indexer/docs/stamp-sales-history-implementation.md) | Sales history construction. |
| [`indexer/docs/MARKET_DATA_OPTIMIZATION_PLAN.md`](../indexer/docs/MARKET_DATA_OPTIMIZATION_PLAN.md) | Market data performance work. |

## Running and syncing

| Document | Covers |
| --- | --- |
| [`docs/DEVELOPMENT.md`](./DEVELOPMENT.md) | Local setup, tooling, code quality gates. |
| [`indexer/docs/local-development.md`](../indexer/docs/local-development.md) | Running the indexer against a local stack. |
| [`docs/BOOTSTRAP.md`](./BOOTSTRAP.md) | Loading a prebuilt snapshot instead of syncing history from genesis. |
| [`indexer/docs/bitcoin.md`](../indexer/docs/bitcoin.md) | Bitcoin node requirements and configuration. |
| [`indexer/docs/counterparty-api-workaround.md`](../indexer/docs/counterparty-api-workaround.md) | Working around the Counterparty API pagination bug. |
| [`indexer/.env.sample`](../indexer/.env.sample) | Every environment variable the indexer reads, with defaults and inline explanations. |

## Reparse and consensus validation

| Document | Covers |
| --- | --- |
| [`indexer/docs/reparse.md`](../indexer/docs/reparse.md) | Running a reparse. |
| [`indexer/docs/reparse-implementation.md`](../indexer/docs/reparse-implementation.md) | How reparse works internally. |
| [`indexer/docs/checkpoint-simulation.md`](../indexer/docs/checkpoint-simulation.md) | Simulating checkpoints for consensus testing. |

## Testing

| Document | Covers |
| --- | --- |
| [`indexer/docs/COVERAGE.md`](../indexer/docs/COVERAGE.md) | Coverage targets and how coverage is measured. |
| [`indexer/docs/TEST_FIXTURES_GUIDE.md`](../indexer/docs/TEST_FIXTURES_GUIDE.md) | Working with test fixtures. |
| [`indexer/docs/DATABASE_FIXTURES_MIGRATION_GUIDE.md`](../indexer/docs/DATABASE_FIXTURES_MIGRATION_GUIDE.md) | Migrating database fixtures. |
| [`indexer/docs/DATABASE_FIXTURES_MIGRATION_LEARNINGS.md`](../indexer/docs/DATABASE_FIXTURES_MIGRATION_LEARNINGS.md) | What went wrong during that migration. |
| [`indexer/docs/thread-safety-testing.md`](../indexer/docs/thread-safety-testing.md) | Thread safety test approach. |
| [`indexer/tests/README.md`](../indexer/tests/README.md) | The test suite itself. |

## Operations

| Document | Covers |
| --- | --- |
| [`ops/INDEXER_SUPERVISION.md`](../ops/INDEXER_SUPERVISION.md) | Supervising the indexer process. |
| [`ops/ALERTING.md`](../ops/ALERTING.md) | Alert detectors, severities, and SNS routing. |
| [`ops/PROD_DEPLOY_CHECKLIST.md`](../ops/PROD_DEPLOY_CHECKLIST.md) | Deployment checklist. |
| [`ops/RDS_PARAMETERS.md`](../ops/RDS_PARAMETERS.md) | Database parameter guidance. |
| [`indexer/docs/performance-history.md`](../indexer/docs/performance-history.md) | Recorded performance changes over time. |

## Release and CI

| Document | Covers |
| --- | --- |
| [`docs/dev/versioning.md`](./dev/versioning.md) | Version scheme and the release workflow. |
| [`indexer/docs/ci-workflows.md`](../indexer/docs/ci-workflows.md) | What each CI workflow does. |

## Contributing to these docs

Keep documentation next to the code it describes. If a change alters anything listed in the
"Where the rules live" table in [`docs/CONSENSUS.md`](./CONSENSUS.md), update that document in
the same pull request.
