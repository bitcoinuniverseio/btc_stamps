# Counterparty dependency recovery

This operational work targets official Counterparty Core v11.4.0,
`e4d1315654b79bb7207cd9f45a8d7b6d5255a290`. It does not modify Bitcoin or
Counterparty transaction interpretation, start a service, grant database access,
or activate a replacement provider.

The existing Signet unit is inactive. Its 11.3 image and preserved datasets must
remain intact. The official 11.4 source is needed after Signet height 325,500.
The immutable release image has been captured, its 307 installed Python and
protocol files match the pinned source, and its native extension imports under
an isolated namespace. That is build evidence, not protocol acceptance.

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
with its real HTTP socket and installed release dependencies. In the isolated
release-image fixture, an accepted response finished after eleven seconds while
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
