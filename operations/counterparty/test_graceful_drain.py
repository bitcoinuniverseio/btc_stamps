import importlib.util
import pathlib
import threading
import unittest

SOURCE = pathlib.Path(__file__).with_name("graceful_drain.py")
SPEC = importlib.util.spec_from_file_location("graceful_drain", SOURCE)
DRAIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRAIN)


class AdmissionTests(unittest.TestCase):
    def test_shutdown_retains_accepted_response_until_its_cleanup_finishes(self):
        entered, release, stopped = threading.Event(), threading.Event(), threading.Event()

        def response():
            try:
                yield b"first"
                entered.set()
                release.wait()
                yield b"committed"
            finally:
                stopped.set()

        application = DRAIN.AdmissionDrain(lambda _env, _start: response())
        body = application({}, lambda *_args: None)
        self.assertEqual(next(body), b"first")
        consumed = []
        worker = threading.Thread(target=lambda: consumed.extend(body))
        worker.start()
        self.assertTrue(entered.wait(1))
        application.close_admission()
        completed = threading.Event()
        waiter = threading.Thread(target=lambda: (application.wait(), completed.set()))
        waiter.start()
        self.assertFalse(completed.wait(0.05))
        release.set()
        worker.join(1)
        waiter.join(1)
        self.assertTrue(stopped.is_set())
        self.assertTrue(completed.is_set())
        self.assertEqual(consumed, [b"committed"])

    def test_new_work_is_rejected_before_application_or_database_entry(self):
        entered = []
        application = DRAIN.AdmissionDrain(lambda *_args: entered.append(True))
        application.close_admission()
        headers = []
        body = application({}, lambda *args: headers.append(args))
        self.assertEqual(b"".join(body), b'{"error":"server_draining"}\n')
        self.assertEqual(headers[0][0], "503 Service Unavailable")
        self.assertEqual(entered, [])
        application.wait()

    def test_generator_failure_closes_owned_response_once(self):
        closed = []

        def response():
            try:
                yield b"first"
                raise ValueError("original response failure")
            finally:
                closed.append(True)

        application = DRAIN.AdmissionDrain(lambda *_args: response())
        body = application({}, lambda *_args: None)
        self.assertEqual(next(body), b"first")
        with self.assertRaisesRegex(ValueError, "original response failure"):
            next(body)
        body.close()
        application.close_admission()
        application.wait()
        self.assertEqual(closed, [True])

    def test_cleanup_failure_cannot_qualify_shutdown(self):
        class Response:
            def __iter__(self):
                return iter([b"body"])

            def close(self):
                raise RuntimeError("retained cleanup failure")

        application = DRAIN.AdmissionDrain(lambda *_args: Response())
        body = application({}, lambda *_args: None)
        with self.assertRaisesRegex(RuntimeError, "retained cleanup failure"):
            list(body)
        application.close_admission()
        with self.assertRaisesRegex(RuntimeError, "shutdown is unqualified"):
            application.wait()

    def test_application_failure_releases_admission_without_hiding_error(self):
        def application(*_args):
            raise ValueError("before response")

        drain = DRAIN.AdmissionDrain(application)
        with self.assertRaisesRegex(ValueError, "before response"):
            drain({}, lambda *_args: None)
        drain.close_admission()
        drain.wait()

    def test_repeated_close_finishes_cleanup_only_once(self):
        closed = []

        class Response:
            def __iter__(self):
                return iter([b"body"])

            def close(self):
                closed.append(True)

        application = DRAIN.AdmissionDrain(lambda *_args: Response())
        body = application({}, lambda *_args: None)
        body.close()
        body.close()
        application.close_admission()
        application.wait()
        self.assertEqual(closed, [True])
        self.assertEqual(list(body), [])

    def test_invalid_response_iterator_still_closes_its_owned_resources(self):
        closed = []

        class Response:
            def __iter__(self):
                raise ValueError("invalid response iterator")

            def close(self):
                closed.append(True)

        application = DRAIN.AdmissionDrain(lambda *_args: Response())
        with self.assertRaisesRegex(ValueError, "invalid response iterator"):
            application({}, lambda *_args: None)
        application.close_admission()
        application.wait()
        self.assertEqual(closed, [True])

    def test_invalid_iterator_and_cleanup_failure_keep_both_errors(self):
        class Response:
            def __iter__(self):
                raise ValueError("invalid response iterator")

            def close(self):
                raise RuntimeError("cleanup failed")

        application = DRAIN.AdmissionDrain(lambda *_args: Response())
        with self.assertRaisesRegex(RuntimeError, "cleanup failed") as failure:
            application({}, lambda *_args: None)
        self.assertIsInstance(failure.exception.__context__, ValueError)
        application.close_admission()
        with self.assertRaisesRegex(RuntimeError, "shutdown is unqualified"):
            application.wait()


if __name__ == "__main__":
    unittest.main()
