"""Prepare an exact, reviewable v11.4.0 patch without editing its checkout."""

import argparse
import difflib
import hashlib
import json
import pathlib
import subprocess

SOURCE_COMMIT = "e4d1315654b79bb7207cd9f45a8d7b6d5255a290"
PREFIX = "counterparty-core/counterpartycore/lib/"


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError("Pinned source shape differs; do not apply an approximate patch")
    return source.replace(old, new, 1)


def prepare(checkout):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    if head != SOURCE_COMMIT or subprocess.check_output(["git", "status", "--porcelain"], cwd=checkout):
        raise RuntimeError("Require the clean, exact pinned upstream checkout")
    result = {}
    for relative in ["api/apiserver.py", "api/apiwatcher.py", "api/wsgi.py", "cli/server.py"]:
        original = subprocess.check_output(["git", "show", "HEAD:" + PREFIX + relative], cwd=checkout).decode()
        changed = original
        if relative == "api/apiserver.py":
            changed = "from counterpartycore.lib.api.graceful_drain import ChildDrain\n" + changed
            changed = replace_once(changed, "        self.process = None\n        self.server_ready_value", "        self.process = None\n        self.child_drain = None\n        self.server_ready_value")
            changed = replace_once(changed, "            self.process.start()\n            logger.info(\"API PID: %s\", self.process.pid)", "            self.process.start()\n            self.child_drain = ChildDrain(self.process, self.stop_event)\n            logger.info(\"API PID: %s\", self.process.pid)")
            begin = changed.index("    def stop(self):\n        logger.info(\"Stopping API Server process...\")")
            end = changed.index("    def has_stopped(self):", begin)
            changed = changed[:begin] + '''    def stop(self):
        logger.info("Stopping API Server process...")
        if self.process is None:
            return
        if self.child_drain is None:
            raise RuntimeError("API child cleanup ownership is unconfirmed")
        self.child_drain.stop()
        logger.info("API Server process completed cleanup naturally.")

''' + changed[end:]
            old = '''        logger.trace("Closing Ledger DB and State DB Connection Pool...")
        LedgerDBConnectionPool().close()
        StateDBConnectionPool().close()

        if watcher is not None:
            watcher.stop(deadline=shutdown_deadline)
'''
            new = '''        if watcher is not None:
            watcher.stop(deadline=shutdown_deadline)

        logger.trace("Closing Ledger DB and State DB Connection Pool...")
        LedgerDBConnectionPool().close()
        StateDBConnectionPool().close()
'''
            changed = replace_once(changed, old, new)
        elif relative == "api/apiwatcher.py":
            changed = replace_once(changed, "from counterpartycore.lib.utils.helpers import deadline_timeout, format_duration", "from counterpartycore.lib.utils.helpers import format_duration")
            start = changed.index("        # Daemon: `stop()` bounds its own join")
            end = changed.index("        logger.debug(\"Initializing API Watcher...\")", start)
            changed = changed[:start] + '''        # Keep the current savepoint and reorg work alive until its owner exits.
        threading.Thread.__init__(self, name="Watcher", daemon=False)
''' + changed[end:]
            start = changed.index("    def stop(self, deadline=None):\n        logger.info(\"Stopping API Watcher thread...\")")
            # The pinned stop method ends this module; reject drift rather than
            # guessing where unrelated code should be removed.
            suffix = changed[start:]
            if "self.join(timeout=deadline_timeout(deadline, 5))" not in suffix or not suffix.rstrip().endswith('logger.info("API Watcher thread stopped.")'):
                raise RuntimeError("Pinned watcher cleanup shape differs")
            changed = changed[:start] + '''    def stop(self, deadline=None):
        logger.info("Stopping API Watcher thread...")
        self.stop_event.set()
        self.join()
        logger.info("API Watcher thread completed cleanup.")
'''
        elif relative == "api/wsgi.py":
            changed = "from counterpartycore.lib.api.graceful_drain import AdmissionDrain\n" + changed
            old = '''class WaitressApplication:
    def __init__(self, app, args=None):
        self.app = app
        self.args = args
        self.server = waitress.server.create_server(
            self.app, host=config.API_HOST, port=config.API_PORT, threads=config.WAITRESS_THREADS
        )'''
            new = '''class WaitressApplication:
    def __init__(self, app, args=None):
        self.app = app
        self.args = args
        self.admission_drain = AdmissionDrain(app)
        self.drain_lock = threading.Lock()
        self.stopping = False
        self.server = waitress.server.create_server(
            self.admission_drain, host=config.API_HOST, port=config.API_PORT,
            threads=config.WAITRESS_THREADS
        )'''
            changed = replace_once(changed, old, new)
            old = '''    def run(self, server_ready_value, shared_backend_height):  # pylint: disable=arguments-differ
        self.server_ready_value = server_ready_value
        CurrentState().set_backend_height_value(shared_backend_height)
        self.current_state_thread = NodeStatusCheckerThread(shared_backend_height)
        self.current_state_thread.start()
        try:
            self.server.run()'''
            new = '''    def run(self, server_ready_value, shared_backend_height):  # pylint: disable=arguments-differ
        self.server_ready_value = server_ready_value
        with self.drain_lock:
            if self.stopping:
                self.server_ready_value.value = 2
                return
            CurrentState().set_backend_height_value(shared_backend_height)
            self.current_state_thread = NodeStatusCheckerThread(shared_backend_height)
            self.current_state_thread.start()
        try:
            self.server.run()'''
            changed = replace_once(changed, old, new)
            old = '''    def stop(self, deadline=None):
        self.current_state_thread.stop(deadline=deadline)
        self.server.close()
        self.server_ready_value.value = 2

    def get_task_dispatcher(self):
        # Waitress'''
            new = '''    def stop(self, deadline=None):
        with self.drain_lock:
            self.stopping = True
            self.admission_drain.close_admission()
            self.admission_drain.wait()
            if self.current_state_thread is not None:
                self.current_state_thread.stop(deadline=deadline)
                self.current_state_thread.join()
            dispatcher = self.server.task_dispatcher
            dispatcher.shutdown(cancel_pending=True, timeout=5)
            with dispatcher.lock:
                while dispatcher.threads:
                    dispatcher.thread_exit_cv.wait()
            self.server.close()
            if self.server_ready_value is not None:
                self.server_ready_value.value = 2

    def get_task_dispatcher(self):
        # Waitress'''
            changed = replace_once(changed, old, new)
        else:
            old = '''        if self.follower_daemon:
            self.follower_daemon.stop()
        if self.asset_conservation_checker:'''
            new = '''        if self.follower_daemon:
            self.follower_daemon.stop()
        if self.api_stop_event:
            self.api_stop_event.set()
        if threading.current_thread() is not self:
            self.join()
        if self.asset_conservation_checker:'''
            changed = replace_once(changed, old, new)
        compile(changed, relative, "exec")
        result[PREFIX + relative] = (original, changed)
    module = pathlib.Path(__file__).with_name("graceful_drain.py").read_text()
    result[PREFIX + "api/graceful_drain.py"] = ("", module)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    changes = prepare(args.source)
    args.output.mkdir(parents=True, exist_ok=False)
    patches, manifest = [], {}
    for name, (old, new) in changes.items():
        patches.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                            fromfile="a/" + name if old else "/dev/null",
                                            tofile="b/" + name))
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new, encoding="utf8", newline="\n")
        manifest[name] = {"upstreamSha256": hashlib.sha256(old.encode()).hexdigest() if old else None,
                          "derivedSha256": hashlib.sha256(new.encode()).hexdigest()}
    (args.output / "counterparty-no-force.patch").write_text("".join(patches), encoding="utf8", newline="\n")
    (args.output / "source-provenance.json").write_text(json.dumps({"upstream": SOURCE_COMMIT, "files": manifest,
        "nativeOrProtocolQualification": False}, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"source": SOURCE_COMMIT, "changedFiles": len(changes), "output": str(args.output),
                      "nativeOrProtocolQualification": False}))
