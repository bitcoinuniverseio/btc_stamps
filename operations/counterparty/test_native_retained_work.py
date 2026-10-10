"""Linux fixture: a retained SQLite transaction must finish before child exit.

The fixture uses only a new private scratch directory and has no chain, wallet,
network or production database dependency. It deliberately exceeds the pinned
Counterparty parent's ten-second forced-exit interval.
"""

import importlib.util
import json
import multiprocessing
import pathlib
import sqlite3
import tempfile
import time
import unittest

SPEC = importlib.util.spec_from_file_location(
    "graceful_drain", pathlib.Path(__file__).with_name("graceful_drain.py")
)
DRAIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRAIN)


def retained_transaction(stop_event, ready, path):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE fixture_outcome (value INTEGER NOT NULL)")
    connection.commit()
    connection.execute("BEGIN")
    connection.execute("INSERT INTO fixture_outcome VALUES (1)")
    ready.set()
    stop_event.wait()
    time.sleep(11)
    connection.commit()
    connection.close()


class NativeRetainedWork(unittest.TestCase):
    def test_natural_exit_preserves_transaction_beyond_old_force_deadline(self):
        context = multiprocessing.get_context("fork")
        root = pathlib.Path(tempfile.mkdtemp(prefix="counterparty-retained-work-"))
        database = root / "isolated.sqlite"
        stop_event, ready = context.Event(), context.Event()
        child = context.Process(target=retained_transaction, args=(stop_event, ready, database))
        child.start()
        self.assertTrue(ready.wait(10), "Own fixture remains HOLD if startup is unconfirmed")
        started = time.monotonic()
        DRAIN.ChildDrain(child, stop_event).stop()
        elapsed = time.monotonic() - started
        self.assertEqual(child.exitcode, 0)
        self.assertFalse(child.is_alive())
        self.assertGreaterEqual(elapsed, 10.5)
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute("SELECT value FROM fixture_outcome").fetchall(), [(1,)])
        receipt = {"exitCode": child.exitcode, "elapsedMs": round(elapsed * 1000),
                   "committedRows": 1, "signalsSent": 0, "forceKillCalls": 0,
                   "networkOrCanonicalDatabaseUsed": False}
        (root / "fixture-receipt.json").write_text(json.dumps(receipt) + "\n", encoding="utf8")
        print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    unittest.main()
