"""loopd.domain.lease — epoch-fenced lease primitives (W2-3).

Single-source helpers for epoch fencing:
  - ``branch_for`` / ``is_epoch_branch`` — working-branch naming that embeds the epoch.
  - ``Lease`` / ``StaleLeaseError`` / ``renew_lease`` / ``is_stale`` — local lease state with
    freshness checks, so a worker self-aborts when its lease has gone stale.
  - ``Watchdog`` — a daemon thread that aborts local work when the lease expires without renewal.

Everything here is stdlib-only and importable without side effects (no threads start on import).
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

_EPOCH_BRANCH_RE = re.compile(r"^(.+)/e(\d+)$")


def branch_for(card_id: str, epoch: int) -> str:
    """Return the epoch-embedded working branch name for a card claim.

    >>> branch_for("FOO", 5)
    'FOO/e5'
    """
    if not isinstance(epoch, int):
        raise TypeError(f"epoch must be an int, got {type(epoch).__name__}")
    if epoch < 0:
        raise ValueError(f"epoch must be >= 0, got {epoch}")
    return f"{card_id}/e{epoch}"


def is_epoch_branch(branch: str):
    """Parse a branch name for the epoch pattern.

    Returns the epoch as ``int`` when the branch matches ``<name>/e<epoch>``, else ``None``.
    ``None`` is falsy so callers can treat it as "not an epoch branch"; a non-None return
    carries the parsed epoch for direct comparison against the card's expected epoch.
    """
    if not isinstance(branch, str):
        return None
    m = _EPOCH_BRANCH_RE.fullmatch(branch)
    if not m:
        return None
    return int(m.group(2))


@dataclass
class Lease:
    """A local copy of a claimed card lease, epoch-fenced."""

    card_id: str
    epoch: int
    lease_until: float
    heartbeat_at: float = 0.0
    ttl_sec: Optional[float] = field(default=None, repr=False)

    @property
    def branch(self) -> str:
        """The working branch bound to this lease (epoch-embedded)."""
        return branch_for(self.card_id, self.epoch)


class StaleLeaseError(Exception):
    """Raised when the local lease is stale and the worker must self-abort.

    A worker that raises/catches this must stop any further writes and abandon the
    claim — the epoch fence is broken and continuing would race an active renewal.
    """


def renew_lease(lease: Lease, now_ts: float, ttl_sec: float) -> None:
    """Renew a lease against the provided wall-clock/parent-clock ``now_ts``.

    Advances ``heartbeat_at`` to ``now_ts`` and ``lease_until`` to ``now_ts + ttl_sec``.
    Mutates ``lease`` in place; returns ``None``.
    """
    if now_ts < lease.heartbeat_at:
        # clock went backwards — refuse to renew rather than silently extend on bad data
        raise StaleLeaseError(
            f"clock moved backwards on lease {lease.card_id}/e{lease.epoch}: "
            f"now_ts={now_ts} < heartbeat_at={lease.heartbeat_at}"
        )
    lease.heartbeat_at = now_ts
    lease.lease_until = now_ts + float(ttl_sec)
    lease.ttl_sec = float(ttl_sec)


def is_stale(lease: Lease, now_ts: float) -> bool:
    """Return ``True`` when ``now_ts`` is beyond the lease's ``lease_until``.

    Stale means the lease expired and, unless renewed, the worker must self-abort.
    """
    return now_ts > lease.lease_until


class Watchdog:
    """Periodic daemon thread that aborts local work if the lease is not renewed.

    The watchdog tracks a monotonic ``_last_renew`` timestamp. On construction and on every
    ``renew()`` call it stamps ``now``. A background daemon thread polls the stamp every
    ``poll_interval`` seconds; if the elapsed time ever exceeds ``ttl_sec`` and the watchdog
    has not been stopped, it calls ``expired_callback()`` (which represents aborting local
    work) and exits.

    It deliberately does NOT kill the caller — ``expired_callback`` is the abort hook. The
    callback runs on the watchdog thread; it should signal the worker (e.g. set a `stop`
    event / raise through a channel) rather than forcibly terminating the process.

    Deterministic and importable with zero side effects: nothing runs until ``start()`` is
    called.
    """

    def __init__(
        self,
        ttl_sec: float,
        expired_callback: Callable[[], None],
        poll_interval: float = 0.25,
    ) -> None:
        if ttl_sec <= 0:
            raise ValueError(f"ttl_sec must be > 0, got {ttl_sec}")
        if poll_interval <= 0:
            raise ValueError(f"poll_interval must be > 0, got {poll_interval}")
        self._ttl = float(ttl_sec)
        self._poll = float(poll_interval)
        self._expired_callback = expired_callback
        self._deadline: Optional[float] = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def renew(self) -> None:
        """Refresh the deadline to now + ``ttl_sec`` (monotonic clock)."""
        with self._lock:
            self._deadline = time.monotonic() + self._ttl

    def _check(self) -> None:
        with self._lock:
            deadline = self._deadline
        if deadline is not None and time.monotonic() > deadline:
            self._expired_callback()

    def start(self) -> None:
        """Begin the daemon watch loop. Idempotent (second call is a no-op)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self._deadline is None:
                self._deadline = time.monotonic() + self._ttl
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="lease-watchdog",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the watchdog loop and join the thread."""
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(self._poll * 4, 1.0))

    def _run(self) -> None:
        while not self._stop.is_set():
            self._check()
            self._stop.wait(self._poll)


def run_watchdog(stop_event, ttl_sec, expired_callback, poll_interval=0.25):
    """Blocking harness that runs a ``Watchdog`` until ``stop_event`` is set.

    Usable in tests/scripts that want the watchdog semantics without manual thread
    plumbing. Returns once ``stop_event`` is set; the callback fires from the watchdog
    thread if the lease goes stale unrenewed.
    """
    wd = Watchdog(ttl_sec, expired_callback, poll_interval)
    wd.start()
    try:
        while not stop_event.wait(poll_interval):
            pass
    finally:
        wd.stop()