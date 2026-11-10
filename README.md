# Bitcoin Stamps indexer

This repository contains the Python indexer and Rust transaction parser for Bitcoin
Stamps, including SRC-20, SRC-721, SRC-721r, OLGA and SRC-101. It is a fork of
[stampchain-io/btc_stamps](https://github.com/stampchain-io/btc_stamps). The protocol
is experimental; see [LICENSE](LICENSE).

## Requirements

- Bitcoin node RPC access, either local or provided by a service.
- MySQL, or the local database included in the development Compose stack.
- Python 3.10–3.12 for native development. Python 3.13 is not consensus-validated;
  see [the consensus reference](docs/CONSENSUS.md).
- A Counterparty node is recommended for production. The default configuration uses
  public Counterparty APIs for XCP asset data.

## Run with Docker Compose

Install [Docker Engine](https://docs.docker.com/engine/install/), then:

```sh
git clone https://github.com/bitcoinuniverseio/btc_stamps.git
cd btc_stamps
cp .env.example .env.local
# Configure the Bitcoin RPC and RDS_* database settings in .env.local.
docker compose up -d
docker compose logs -f indexer
```

The default development overlay runs the indexer and a local MySQL database with a
persistent `db_data` volume. `docker compose down` stops the stack. The production
overlay (`docker-compose.prod.yml`) targets managed MySQL and is not yet deployed;
production currently runs natively via systemd. See `make help` for Compose shortcuts.

For container development and registry images, see `indexer/run-container.sh --help`
and [indexer/README.md](indexer/README.md). Avoid cleanup options unless you have
verified which containers, images and volumes they remove.

## Native development

Install `libgmp-dev` and Poetry 2.1.1, then from the repository root:

```sh
cd indexer
poetry install
poetry run task build
poetry run indexer
```

Configure MySQL, Bitcoin node and Counterparty settings before running the indexer.
See [CONTRIBUTING.md](CONTRIBUTING.md) and [development documentation](docs/DEVELOPMENT.md)
for checks and test setup. Changes to parsing and ledger behavior require particular
care because indexers must agree on consensus hashes.

The optional ZeroMQ block notification delay is configured with
`ZMQ_NOTIFICATION_DELAY` in seconds (default `5`); it gives Counterparty time to
process a block before the indexer fetches it.

## Documentation

- [Documentation map](docs/README.md)
- [Consensus rules and activation heights](docs/CONSENSUS.md)
- [Architecture](docs/ARCHITECTURE.md), [protocol formats](docs/PROTOCOLS.md), and
  [database schema](docs/DATABASE.md)
- [Technical whitepaper](docs/whitepaper/index.md) and
  [Stamps Improvement Proposals](https://bitcoinstamps.xyz/en/protocols/sips)
- [Bitcoin Stamps protocol site](https://bitcoinstamps.xyz),
  [Stampchain explorer](https://stampchain.io/), and
  [developer API documentation](https://stampchain.io/docs)

## Releases

Maintainers cut releases using the workflow described in
[versioning](docs/dev/versioning.md). The Docker auto-publish workflow signs release
images and records verification information in the release. Verify an image against the
workflow identity and digest recorded for that release before running it.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development and review process and
[SECURITY.md](SECURITY.md) for reporting security or consensus issues privately.
