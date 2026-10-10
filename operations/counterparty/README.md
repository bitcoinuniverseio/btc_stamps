# Counterparty dependency recovery

This operational work now targets official Counterparty Core v11.5.0,
`8aab989157019e62423cd959b8571c7daf748d56`. The security release requires
replay from Signet block 324,359 (Mainnet block 969,320). At the preserved
Signet database height 325,199, 11.4 is no longer a supported current parser.
The patch preserves 11.5 transaction interpretation and its mempool progress
handoff. It prepares source without starting a service, granting database access,
or activating a replacement provider.

The existing 11.3 image and original datasets remain preserved. Qualification
uses a separate copy and the release's own upgrade actions. The captured 11.5
release image's 312 installed Python and protocol files match the pinned raw Git
source; compiled Rust source equivalence and full chain-provider acceptance
remain unqualified.

Earlier 11.4 qualification remains historical evidence: 307 installed source
files matched its release, and isolated native migration completed at height
325,199. That success does not qualify 11.4 after the 11.5 activation. Keep those
receipts rather than relabeling them as current release evidence.

The pinned upstream parent kills its API child after ten seconds. Its child also
interrupts its watcher and spends an eight-second cleanup budget. Before adoption,
the deployment needs source-supported admission closure and waits for accepted
responses, parser work and watcher transactions before closing database pools.
Unfinished or failed cleanup must remain an explicit unqualified state.

`graceful_drain.py` supplies the admission and owned-child wait primitives.
`prepare_source_patch.py` produces an exact six-file patch for the pinned server
and records every upstream and derived file hash. The patch is prepared, without
live adoption. Full source/native gates remain required; these files alone do
not fix a live service. `test_graceful_drain.py` verifies accepted-response cleanup, error
propagation and rejection before application entry. The Linux fixture
`test_native_retained_work.py` retains a real SQLite transaction beyond the old
ten-second deadline and checks its committed readback and natural child exit.
`test_source_integration.py` exercises the actual derived methods for API-only
stop ordering, a retained watcher transaction and stopping before serving starts;
it also verifies that unrelated declarations remain intact. The operational CI
job fetches the exact upstream commit and runs these controls on Linux.

`native_waitress_transport.py` additionally exercises the derived Waitress class
with its real HTTP socket and installed release dependencies. In the earlier isolated
11.4 release-image fixture, an accepted response finished after eleven seconds while
new admission returned 503, then the server and dispatcher exited naturally.
The fixture also starts the actual derived watcher and verifies that a real
SQLite savepoint commits after eleven seconds before the watcher closes its
connections. Earlier runs exposed a forbidden WSGI Connection header and a
worker wakeup race; the corrected final run passed without cleanup diagnostics.
This fixture supplies `derived_wsgi.py` and `derived_apiwatcher.py` from the
generated patch and does not establish full chain-provider acceptance. The
legacy JSON-RPC server uses the same admission accounting when enabled; its real
HTTP fixture retains an eleven-second response, returns 503 to new work, and
exits naturally. Stopping before startup cannot create a listener afterward.

Keep canonical mounts out of qualification namespaces. Pin network, genesis,
source image, protected cookie reference, sole producer and database epoch before
any provider promotion. Keep listeners on loopback, preserve catch-up and reorg
work, use infinite start/stop timeouts with no forced kill or restart, and retain
an executable rollback to a qualified artifact and configuration.
