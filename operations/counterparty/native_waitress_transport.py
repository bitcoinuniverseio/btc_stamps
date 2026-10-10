"""Actual pinned Waitress socket and generated class; no chain or canonical DB."""
import http.client
import importlib.util
import logging
import pathlib
import sys
import threading
import time
import types
import unittest


class NativeWaitressDrain(unittest.TestCase):
    def test_actual_http_response_finishes_after_old_force_deadline(self):
        root = pathlib.Path(__file__).parent
        for name, path in [
            ("counterpartycore.lib.api.graceful_drain", root / "graceful_drain.py"),
            ("derived_waitress", root / "derived_wsgi.py"),
        ]:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        wsgi = sys.modules["derived_waitress"]
        wsgi.config.API_HOST, wsgi.config.API_PORT = "127.0.0.1", 0
        wsgi.config.WAITRESS_THREADS = 2
        wsgi.log.re_set_up = lambda *_args, **_kwargs: logging.getLogger("fixture")
        entered, closing, finished = threading.Event(), threading.Event(), threading.Event()

        def application(_environ, start):
            start("200 OK", [("Content-Type", "text/plain")])
            try:
                entered.set()
                self.assertTrue(closing.wait(10))
                time.sleep(11)
                yield b"accepted-response-completed"
            finally:
                finished.set()

        server = wsgi.WaitressApplication(application)
        server.server_ready_value = types.SimpleNamespace(value=1)
        port = server.server.effective_port
        serving = threading.Thread(target=server.server.run)
        serving.start()
        response = []

        def read():
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            try:
                connection.request("GET", "/retained")
                result = connection.getresponse()
                response.append((result.status, result.read()))
            finally:
                connection.close()

        request = threading.Thread(target=read)
        request.start()
        self.assertTrue(entered.wait(10))
        began = time.monotonic()
        stop = threading.Thread(target=server.stop)
        stop.start()
        deadline = time.monotonic() + 5
        while not server.admission_drain._closing and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(server.admission_drain._closing)
        rejected = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        rejected.request("GET", "/new")
        result = rejected.getresponse()
        self.assertEqual(result.status, 503)
        self.assertIn(b"server_draining", result.read())
        rejected.close()
        closing.set()
        request.join(30)
        stop.join(30)
        serving.join(10)
        self.assertFalse(request.is_alive() or stop.is_alive() or serving.is_alive())
        self.assertTrue(finished.is_set())
        self.assertEqual(response, [(200, b"accepted-response-completed")])
        self.assertGreaterEqual(time.monotonic() - began, 10.5)
        self.assertEqual(server.server_ready_value.value, 2)
        self.assertFalse(server.server.task_dispatcher.threads)


if __name__ == "__main__":
    unittest.main()
