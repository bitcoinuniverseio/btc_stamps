"""Exercise exact patched server methods against real task/thread lifecycles."""

import ast
import importlib.util
import pathlib
import threading
import types
import unittest

SPEC = importlib.util.spec_from_file_location("prepare_patch", pathlib.Path(__file__).with_name("prepare_source_patch.py"))
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class Logger:
    def __getattr__(self, _name):
        return lambda *_args: None


def source_method(source, class_name, method_name, environment):
    tree = ast.parse(source)
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
    namespace = dict(environment)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), "pinned-source-method", "exec"), namespace)
    return namespace[method_name]


class SourceIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os

        cls.checkout = pathlib.Path(os.environ["COUNTERPARTY_PINNED_SOURCE"])
        cls.changes = PREPARE.prepare(cls.checkout)

    def test_api_only_owner_requests_child_stop_before_joining_its_server_thread(self):
        source = self.changes[PREPARE.PREFIX + "cli/server.py"][1]
        stop = source_method(source, "CounterpartyServer", "stop", {
            "logger": Logger(), "threading": threading,
            "CurrentState": lambda: types.SimpleNamespace(set_stopping=lambda: None),
            "rsfetcher": types.SimpleNamespace(RSFetcher=lambda: types.SimpleNamespace(stop=lambda: None)),
        })
        event = threading.Event()
        finished = threading.Event()
        owner_thread = threading.Thread(target=lambda: (event.wait(), finished.set()))
        owner_thread.start()
        owner = types.SimpleNamespace(stopped=False, stop_requested=False, api_stop_event=event,
            follower_daemon=None, asset_conservation_checker=None, backend_height_thread=None,
            api_status_poller=None, apiserver_v1=None, apiserver_v2=None, pool_monitor=None,
            periodic_profiler=None, mem_profiler=None)

        def join():
            self.assertTrue(event.is_set(), "API-only thread must receive its stop event before join")
            owner_thread.join(1)
            self.assertFalse(owner_thread.is_alive())

        owner.join = join
        stop(owner)
        self.assertTrue(finished.is_set())
        self.assertTrue(owner.stopped)

    def test_watcher_waits_for_its_current_transaction_without_interrupting_it(self):
        source = self.changes[PREPARE.PREFIX + "api/apiwatcher.py"][1]
        stop = source_method(source, "APIWatcher", "stop", {"logger": Logger()})
        event, release, completed = threading.Event(), threading.Event(), threading.Event()
        worker = threading.Thread(target=lambda: (release.wait(), completed.set()))
        worker.start()
        interrupts = []
        watcher = types.SimpleNamespace(stop_event=event, state_db=types.SimpleNamespace(interrupt=lambda: interrupts.append(True)),
                                        ledger_db=types.SimpleNamespace(interrupt=lambda: interrupts.append(True)), join=worker.join)
        waiter = threading.Thread(target=lambda: stop(watcher, deadline=0))
        waiter.start()
        self.assertTrue(event.wait(1))
        self.assertTrue(waiter.is_alive())
        release.set()
        waiter.join(1)
        self.assertTrue(completed.is_set())
        self.assertFalse(waiter.is_alive())
        self.assertEqual(interrupts, [])

    def test_waitress_stopped_before_run_cannot_open_a_new_serving_loop(self):
        source = self.changes[PREPARE.PREFIX + "api/wsgi.py"][1]
        run = source_method(source, "WaitressApplication", "run", {"CurrentState": lambda: self.fail("No startup after stop")})
        ready = types.SimpleNamespace(value=0)
        server = types.SimpleNamespace(server_ready_value=None, drain_lock=threading.Lock(), stopping=True)
        run(server, ready, None)
        self.assertEqual(ready.value, 2)

    def test_patch_retains_all_unrelated_functions_and_classes(self):
        def declarations(source):
            return {(type(node).__name__, node.name) for node in ast.walk(ast.parse(source))
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

        for name, (old, new) in self.changes.items():
            if old:
                self.assertEqual(declarations(old), declarations(new), name)


if __name__ == "__main__":
    unittest.main()
