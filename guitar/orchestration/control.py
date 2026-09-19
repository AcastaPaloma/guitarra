"""Cooperative controls for fake runs. NOT a hardware emergency stop.

A provider request already in flight cannot be cancelled by this object. The runner
checks again before dispatch and discards pending calls after cancellation/expiry.
"""
import threading
import time


class RunControl:
    def __init__(self):
        self._condition = threading.Condition()
        self._pause_requested = False
        self._waiting = False
        self._cancelled = False

    def pause(self) -> None:
        with self._condition:
            self._pause_requested = True
            self._condition.notify_all()

    def resume(self) -> None:
        with self._condition:
            self._pause_requested = False
            self._condition.notify_all()

    def cancel(self) -> None:
        with self._condition:
            self._cancelled = True
            self._condition.notify_all()

    def snapshot(self) -> dict:
        with self._condition:
            return {"pause_requested": self._pause_requested, "paused": self._waiting,
                    "cancel_requested": self._cancelled}

    def wait(self, deadline: float, clock=time.monotonic) -> str | None:
        with self._condition:
            while self._pause_requested and not self._cancelled:
                self._waiting = True
                remaining = deadline - clock()
                if remaining <= 0:
                    self._waiting = False
                    return "paused_budget_exhausted"
                self._condition.wait(timeout=min(remaining, 0.2))
            self._waiting = False
            if self._cancelled:
                return "cancelled"
            if clock() >= deadline:
                return "expired_model_response"
            return None
