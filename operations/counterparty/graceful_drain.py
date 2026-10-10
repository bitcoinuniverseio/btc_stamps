"""Drain primitives for the pinned Counterparty deployment, without forced exits.

These primitives do not execute a server, open a database, or change a process
until the owner explicitly invokes them. The deployment patch must close new
HTTP admission and finish its watcher/parser work before closing database pools.
"""

from threading import Condition, Lock, RLock


class DrainingResponse:
    def __init__(self, body, release):
        self._body = body
        self._iterator = iter(body)
        self._release = release
        self._closed = False
        self._advance_lock = RLock()

    def __iter__(self):
        return self

    def __next__(self):
        with self._advance_lock:
            if self._closed:
                raise StopIteration
            try:
                return next(self._iterator)
            except BaseException:
                self.close()
                raise

    def close(self):
        with self._advance_lock:
            if self._closed:
                return
            self._closed = True
            clean = False
            try:
                close = getattr(self._body, "close", None)
                if close is not None:
                    close()
                clean = True
            finally:
                self._release(clean)


class AdmissionDrain:
    """Track accepted WSGI work through response completion and cleanup."""

    def __init__(self, application):
        self._application = application
        self._condition = Condition()
        self._closing = False
        self._active = 0
        self._cleanup_failed = False

    def __call__(self, environ, start_response):
        with self._condition:
            if self._closing:
                accepted = False
            else:
                self._active += 1
                accepted = True
        if not accepted:
            body = b'{"error":"server_draining"}\n'
            start_response(
                "503 Service Unavailable",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                    ("Connection", "close"),
                    ("Retry-After", "1"),
                ],
            )
            return [body]
        try:
            body = self._application(environ, start_response)
        except BaseException:
            self._release()
            raise
        try:
            return DrainingResponse(body, self._release)
        except BaseException:
            clean = False
            try:
                close = getattr(body, "close", None)
                if close is not None:
                    close()
                clean = True
            finally:
                self._release(clean)
            raise

    def _release(self, clean=True):
        with self._condition:
            if self._active <= 0:
                raise RuntimeError("Drain accounting underflow")
            self._active -= 1
            self._cleanup_failed |= not clean
            self._condition.notify_all()

    def close_admission(self):
        with self._condition:
            self._closing = True

    def wait(self):
        with self._condition:
            while self._active:
                self._condition.wait()
            if self._cleanup_failed:
                raise RuntimeError("Response cleanup failed; shutdown is unqualified")


class ChildDrain:
    """Request the child's existing event-driven cleanup and retain ownership.

    The multiprocessing process handle, rather than a bare PID, owns the wait.
    No signal or deadline can turn unfinished work into a successful shutdown.
    Concurrent/repeated calls share the same event and serialized natural wait.
    """

    def __init__(self, process, stop_event):
        self._process = process
        self._stop_event = stop_event
        self._wait_lock = Lock()

    def stop(self):
        self._stop_event.set()
        with self._wait_lock:
            self._process.join()
            if self._process.exitcode is None:
                raise RuntimeError("Child cleanup remains unconfirmed")
            if self._process.exitcode != 0:
                raise RuntimeError("Child exited without successful cleanup")
