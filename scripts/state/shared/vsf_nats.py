#!/usr/bin/env python3
"""vsf_nats.py — VSF shared resilient NATS helper.

Usage:
    import vsf_nats
    nc = await vsf_nats.connect_resilient("nats://host:4222", name="my-service")

Three-layer resilience (see docs/spec/NATS-RESILIENCE-FIX.spec.vsm §fix_design):
  Layer 1: reconnect INFINITO (max_reconnect_attempts=-1) + callbacks ruidosos
           (disconnected/reconnected/error loguean fuerte).
           closed_cb → CRITICAL + os._exit(1) (fail-loud, inalcanzable con -1 pero defensivo).
  Layer 2: publish seguro con timeout (asyncio.wait_for + retry en el caller).
  Layer 3: systemd WATCHDOG helper (sd_notify) sin dep externas.
"""
import asyncio
import logging
import os
import socket
import sys
import typing

logger = logging.getLogger("vsf_nats")

# Auto-configure logger: add stdout handler if none exists.
# Bridges use print(), not logging, so vsf_nats logs via logger.info() would be
# silently dropped by Python's "last resort" handler (WARNING+ only).
# This ensures ALL vsf_nats diagnostics (RECONNECTED, readback, errors) are visible.
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    # Message already includes [vsf_nats] prefix from 'pref' variable;
    # just pass through to avoid doubling.
    _h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Layer 3 — systemd watchdog helper (no external deps)
# ---------------------------------------------------------------------------

_WATCHDOG_USEC = None  # cached value from systemd, or 0 if not under systemd


def _get_watchdog_usec() -> int:
    """Return WATCHDOG_USEC from systemd (microseconds), or 0 if not under watchdog."""
    global _WATCHDOG_USEC
    if _WATCHDOG_USEC is None:
        raw = os.environ.get("WATCHDOG_USEC", "")
        try:
            _WATCHDOG_USEC = int(raw) if raw else 0
        except (ValueError, TypeError):
            _WATCHDOG_USEC = 0
    return _WATCHDOG_USEC


def _notify_socket_path() -> str | None:
    """Return the NOTIFY_SOCKET path, or None if not under systemd."""
    raw = os.environ.get("NOTIFY_SOCKET", "")
    return raw if raw else None


def sd_notify(state: str) -> None:
    """Send a notification to systemd. Usage: sd_notify('READY=1'), sd_notify('WATCHDOG=1').

    Pure-Python, no external deps. Writes to $NOTIFY_SOCKET (datagram or stream).
    Silently no-ops if NOTIFY_SOCKET is not set (not running under systemd).

    Handles abstract sockets (@ prefix → Linux abstract namespace with \\0).
    Keeps logger traffic minimal — WATCHDOG=1 runs every 10s and is deliberately
    silent except on failure.
    """
    sock_path = _notify_socket_path()
    if not sock_path:
        return  # not under systemd → no-op

    try:
        # Handle abstract socket (@ → \0 for Linux abstract namespace)
        if sock_path.startswith("@"):
            addr = b"\0" + sock_path[1:].encode()
        else:
            addr = sock_path.encode()

        # systemd supports both DGRAM and STREAM; DGRAM is simpler.
        # SOCK_CLOEXEC is intentionally omitted: the socket fd should not
        # survive exec (systemd closes NOTIFY_SOCKET on exec anyway, but
        # being explicit prevents fd leaks into child processes).
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            sock.connect(addr)
            sock.sendall(state.encode())
        finally:
            sock.close()
    except OSError as e:
        logger.warning("sd_notify(%s) failed: %s", state, e)


def sd_notify_ready() -> None:
    """Notify systemd that the service is ready. Call AFTER successful init."""
    sd_notify("READY=1")
    wd = _get_watchdog_usec()
    if wd > 0:
        logger.info("[vsf_nats] systemd watchdog active: WATCHDOG_USEC=%d (%.1fs)", wd, wd / 1_000_000)
    else:
        logger.info("[vsf_nats] systemd watchdog NOT configured — falling back to process-liveness only")


def sd_notify_watchdog() -> None:
    """Ping systemd watchdog. Call on every successful tick/publish cycle."""
    sd_notify("WATCHDOG=1")


# ---------------------------------------------------------------------------
# Layer 1 — resilient connection helper
# ---------------------------------------------------------------------------

async def connect_resilient(
    url: str,
    name: str | None = None,
    on_reconnect: "typing.Callable[[], typing.Awaitable[None]] | None" = None,
    *,
    log_prefix: str = "",
) -> "nats.NATSClient":
    """Connect to NATS with reconnection handling.

    TWO-PHASE DESIGN (nats-py 2.15.0 compatible — NO retry_on_failed_connect):

    Phase 1 — Time-bounded initial connect:
      Uses max_reconnect_attempts=1 so nats.connect() NEVER hangs. If NATS is
      unreachable, each attempt fails in ~5s (connect_timeout). Up to 3 quick
      attempts. If none succeed → Phase 2.

    Phase 2 — READY + background reconnect:
      Sends sd_notify('READY=1') IMMEDIATELY so systemd NEVER sees 'activating'
      waiting for NATS. Then enters a manual reconnect loop: each iteration
      tries nats.connect() with max_reconnect_attempts=1 (time-bounded ~5s).
      Sleeps 2s between attempts. The caller's health_probe and systemd watchdog
      govern REAL liveness — no NATS connection → no heartbeat → restart.

    POST-CONNECT (after Phase 1 or 2 succeeds):
      Patches nc.options[\"max_reconnect_attempts\"] = -1 so that if the
      connection drops AFTER being established, nats-py reconnects infinitely
      in the background (standard nats-py reconnect behavior). The closed_cb
      fail-loud (os._exit(1)) is a LAST RESORT if reconnect genuinely exhausts.

    Args:
        url: NATS URL (e.g. nats://user:pass@host:4222 or nats://token@host).
        name: Optional client name (appears in NATS server connz).
        on_reconnect: Optional async callable invoked AFTER successful reconnect.
            Signature: async def cb() -> None. Use to re-init state if needed.
        log_prefix: Optional prefix for log messages.

    Returns:
        Connected NATS client instance (with post-connect infinite reconnect).

    Raises:
        (never — Phase 2 loops forever until NATS is reachable)
    """
    import nats  # lazy import — allow module to be loaded without nats installed
    import nats.errors as nats_err

    pref = f"[{log_prefix}]" if log_prefix else "[vsf_nats]"

    # ── Shared state ──
    _closing_intentionally = False
    _reconnect_count = 0

    async def _disconnected_cb():
        nonlocal _reconnect_count
        _reconnect_count += 1
        logger.warning("%s NATS DISCONNECTED — attempting reconnect (#%d, infinite)", pref, _reconnect_count)

    async def _reconnected_cb():
        logger.info(
            "%s NATS RECONNECTED (#%d) — nc.is_connected=%s",
            pref, _reconnect_count, True,
        )
        if on_reconnect is not None:
            try:
                await on_reconnect()
            except Exception as e:
                logger.error("%s on_reconnect callback failed: %s", pref, e)

    async def _error_cb(e):
        # log type + repr — many nats-py errors have an empty str() (auth/timeout),
        # which is exactly what hid the cause of 'activating' in the 101 pilot.
        logger.error("%s NATS error: %s: %r", pref, type(e).__name__, e)

    async def _closed_cb():
        nonlocal _closing_intentionally
        if _closing_intentionally:
            logger.info("%s NATS connection closed (intentional)", pref)
            return
        logger.critical(
            "%s NATS connection CLOSED unexpectedly — "
            "infinite reconnect exhausted or server gone. "
            "Exiting so systemd restarts.",
            pref,
        )
        sd_notify("STOPPING=1")
        os._exit(1)

    # ── Shared connect options ──
    # Design: nats-py 2.15.0 connect() blocks until connected OR
    # max_reconnect_attempts exhausted. Using 1 here so each call is
    # time-bounded (~connect_timeout=5s). The reconnect_loop below
    # handles indefinite retries.
    _BASE_OPTS = dict(
        servers=url,
        name=name,
        max_reconnect_attempts=1,   # only 1 try per connect() call
        connect_timeout=5,          # max wait per TCP/handshake attempt
        allow_reconnect=True,       # enable reconnect AFTER initial connect
        reconnect_time_wait=2,
        disconnected_cb=_disconnected_cb,
        reconnected_cb=_reconnected_cb,
        error_cb=_error_cb,
        closed_cb=_closed_cb,
    )

    def _patch_client(nc: "nats.NATSClient") -> None:
        """Patch a connected client: drain/close hijack + post-connect infinite reconnect.

        AFTER nats.connect() returns a connected client, we:
        1. Patch drain()/close() to set _closing_intentionally=True so
           closed_cb doesn't os._exit(1) on intentional shutdown.
         2. Set nc.options[\"max_reconnect_attempts\"] = -1 so that subsequent
           disconnections trigger infinite background reconnection (the
           standard nats-py behavior we actually want).
        """
        nonlocal _closing_intentionally

        # Set infinite reconnect for POST-CONNECT phase — once the initial
        # connection is established, nats-py will retry indefinitely if
        # the server drops.
        try:
            nc.options["max_reconnect_attempts"] = -1
            actual = nc.options.get("max_reconnect_attempts", "GET_FAILED")
            logger.info(
                "%s Post-connect: max_reconnect_attempts=%s (confirmed readback)",
                pref, actual,
            )
        except Exception as e:
            logger.warning(
                "%s Post-connect: FAILED to set max_reconnect_attempts: %s: %r. "
                "Infinite reconnect NOT active — fallback to nats-py default (%d retries).",
                pref, type(e).__name__, e, _BASE_OPTS["max_reconnect_attempts"],
            )

        # Patch drain/close to prevent closed_cb fail-loud on intentional exit
        _orig_drain = nc.drain
        _orig_close = nc.close

        async def _patched_drain(*args, **kw):
            nonlocal _closing_intentionally
            _closing_intentionally = True
            return await _orig_drain(*args, **kw)

        async def _patched_close(*args, **kw):
            nonlocal _closing_intentionally
            _closing_intentionally = True
            return await _orig_close(*args, **kw)

        nc.drain = _patched_drain
        nc.close = _patched_close

    # ── Phase 1: Time-bounded initial connect ──
    # Each attempt is capped by max_reconnect_attempts=1 so nats.connect()
    # returns (or raises) within ~connect_timeout seconds. NATS unreachable
    # at startup → fast failure, no hang, no 'activating' at this stage.
    for attempt in range(3):
        try:
            nc = await nats.connect(**_BASE_OPTS)
            _patch_client(nc)
            logger.info(
                "%s NATS connected (attempt %d): %s",
                pref, attempt + 1, url,
            )
            return nc
        except nats_err.NoServersError:
            logger.warning(
                "%s Connect attempt %d: NATS unreachable (NoServersError)",
                pref, attempt + 1,
            )
        except (OSError, asyncio.TimeoutError, AttributeError) as e:
            logger.warning(
                "%s Connect attempt %d: NATS unreachable (%s: %r)",
                pref, attempt + 1, type(e).__name__, e,
            )
        except Exception as e:
            logger.warning(
                "%s Connect attempt %d: unexpected error %s: %r",
                pref, attempt + 1, type(e).__name__, e,
            )
        await asyncio.sleep(1)

    # ── Phase 2: READY=1 — NEVER block 'activating' ──
    # All 3 quick attempts failed. Send READY immediately so systemd goes to
    # 'active (running)' even without NATS. The health_probe/watchdog govern
    # REAL liveness: no NATS → no heartbeat → watchdog restart.
    logger.warning(
        "%s NATS unreachable after 3 attempts — sending READY=1, entering "
        "background reconnect loop", pref,
    )
    sd_notify_ready()

    # ── Phase 3: Manual reconnect loop (time-bounded per iteration) ──
    # Each iteration tries nats.connect() with max_reconnect_attempts=1
    # (~5s timeout per try). Sleeps 2s between tries. This is NOT infinite
    # reconnect in the nats-py sense — it's our own reconnect loop that
    # never blocks 'activating'.
    while True:
        try:
            nc = await nats.connect(**_BASE_OPTS)
            _patch_client(nc)
            logger.info(
                "%s NATS connected (reconnect loop): %s (connected=%s)",
                pref, url, nc.is_connected,
            )
            return nc
        except nats_err.NoServersError:
            logger.info("%s Reconnect: NATS still unreachable", pref)
        except (OSError, asyncio.TimeoutError, AttributeError) as e:
            logger.info("%s Reconnect: NATS unreachable (%s: %r)", pref, type(e).__name__, e)
        except Exception as e:
            logger.info("%s Reconnect: unexpected %s: %r", pref, type(e).__name__, e)
        await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# Layer 3b — health probe helper (for publishers who publish less often
#            than WatchdogSec, so the probe keeps the watchdog alive)
# ---------------------------------------------------------------------------

PROBE_INTERVAL = 10   # seconds
FLUSH_TIMEOUT  = 5.0  # seconds


def start_health_probe(
    nc: "nats.NATSClient",
    *,
    probe_interval: float = PROBE_INTERVAL,
    flush_timeout: float = FLUSH_TIMEOUT,
    stop_event: asyncio.Event | None = None,
    name: str = "",
) -> asyncio.Task:
    """Start a background health probe that keeps systemd watchdog alive.

    Every `probe_interval` seconds, performs `nc.flush(timeout=flush_timeout)`.
    If the flush succeeds AND nc.is_connected → calls sd_notify_watchdog().
    If flush fails (NATS down, reconnect in progress) → NO heartbeat →
    systemd watchdog expires → process is restarted.

    This is the PROBE-GATED design: heartbeat only when NATS connection is
    actually healthy. A process with live connection but hung event loop
    will also get killed — the flush timeout bounds the max delay.

    Call right after connect_resilient() succeeds. The returned Task should
    be cancelled on shutdown.

    Args:
        nc: Connected NATS client.
        probe_interval: Seconds between flush probes (default 10).
        flush_timeout: Max seconds for each flush (default 5).
        stop_event: Optional asyncio.Event to signal stop. If None, runs
            indefinitely (caller must cancel the task).
        name: Optional label for probe log prefix.

    Returns:
        The asyncio.Task for the probe loop. Cancel on shutdown.
    """
    pref = f"[{name}]" if name else "[probe]"

    async def _probe_loop():
        while True:
            if stop_event is not None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=probe_interval)
                    return  # stop_event signaled
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(probe_interval)

            try:
                if nc.is_connected:
                    await asyncio.wait_for(nc.flush(), timeout=flush_timeout)
                    if nc.is_connected:
                        sd_notify_watchdog()
            except Exception:
                # flush failed → no heartbeat → watchdog kills process
                pass

    task = asyncio.create_task(_probe_loop())
    logger.info(
        "%s health probe started: interval=%.1fs flush_timeout=%.1fs",
        pref, probe_interval, flush_timeout,
    )
    return task


# ---------------------------------------------------------------------------
# Layer 2 — safe publish helper
# ---------------------------------------------------------------------------

PUBLISH_TIMEOUT = 5.0  # seconds — climate tick=5s, 30s would block ~6 ticks


async def publish_safe(
    nc: "nats.NATSClient",
    subject: str,
    payload: bytes = b"",
    *,
    timeout: float = PUBLISH_TIMEOUT,
    log_prefix: str = "",
) -> bool:
    """Publish to NATS with timeout and resilience.

    Never hangs or crashes the event loop. On transient error (disconnect,
    timeout, OutboundBufferLimitError), logs and returns False so the
    caller can continue its loop.

    Args:
        nc: NATS client.
        subject: Subject to publish to.
        payload: Message bytes.
        timeout: Max seconds to wait for publish to complete.
        log_prefix: Optional prefix for log messages.

    Returns:
        True if publish completed (or queued successfully during reconnect),
        False on transient error.
    """
    pref = f"[{log_prefix}]" if log_prefix else "[vsf_nats]"
    try:
        await asyncio.wait_for(nc.publish(subject, payload), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        logger.warning("%s publish TIMEOUT (%s, %.1fs) — reconnecting may be in progress", pref, subject, timeout)
        return False
    except Exception as e:
        # OutboundBufferLimitError, ConnectionClosedError, etc.
        logger.warning("%s publish ERROR (%s): %s — will retry next cycle", pref, subject, e)
        return False


# ---------------------------------------------------------------------------
# Alias per NATS-SHARED-HELPER (docs/spec/nats_auth_remediation/spec.vsm
# §systemic): one authed connect helper per language, used by ALL clients.
# Rust: vsf_agent::nats::connect (exists). Python: vsf_nats.connect().
# connect_resilient is the full-featured implementation; `connect` is the
# mandated entry point so future auth changes touch ONE place.
# ---------------------------------------------------------------------------

async def connect(url: str | None = None, *, name: str = "vsf", **kw) -> "typing.Any":
    """Mandated Python NATS connect helper (mirror of Rust vsf_agent::nats::connect).

    Reads NATS_URL from env when url is None. Wraps connect_resilient so
    every caller gets the three-layer resilience (reconnect, safe publish,
    systemd watchdog helpers) with zero per-caller config.
    """
    if url is None:
        url = os.environ.get("NATS_URL", "nats://localhost:4222")
    return await connect_resilient(url, name=name, **kw)
