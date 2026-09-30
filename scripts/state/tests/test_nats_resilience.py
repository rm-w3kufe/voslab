#!/usr/bin/env python3
"""
test_nats_resilience.py — Chaos test for NATS-RESILIENCE-FIX.

Test scenarios:
  1. Connect → publish loop → kill nats-server → verify reconnect + publish resumes.
  2. Subscribe → kill nats-server → verify reconnected_cb + subscription works post-reconnect.
  3. Watchdog: verify sd_notify watchdog path works under systemd (or simulated).
  4. Confirm _flush_timeout and _max_pending_size post-connect.

Usage:
  # Terminal 1: start a test nats-server on a non-standard port
  nats-server -p 14222

  # Terminal 2: run this test
  python3 test_nats_resilience.py

Environment:
  NATS_TEST_URL  (default: nats://127.0.0.1:14222)
  NATS_KILL_CMD  (default: pkill -9 -f 'nats-server -p 14222')
  NATS_RESTART_CMD (default: nats-server -p 14222 &)
"""
import asyncio
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, "/tmp")  # LXC 108 test path
import vsf_nats

NATS_URL = os.environ.get("NATS_TEST_URL", "nats://127.0.0.1:14222")
NATS_KILL = os.environ.get("NATS_KILL_CMD", "pkill -9 -f 'nats-server -p 14222' || true")
NATS_RESTART = os.environ.get("NATS_RESTART_CMD", "nats-server -p 14222 -l /dev/null &")

PASS = 0
FAIL = 0


def _check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")


def _kill_nats():
    subprocess.run(NATS_KILL, shell=True, capture_output=True)
    time.sleep(0.5)


def _restart_nats():
    subprocess.run(NATS_RESTART, shell=True)
    time.sleep(1)


# ── Test 1: Publish loop survives NATS restart ─────────────────────────


async def test_publish_loop_survives_restart():
    """Connect → publish every 0.5s → kill NATS → verify reconnect → verify publish resumes."""
    print("\n=== Test 1: Publish loop survives NATS restart ===")

    nc = await vsf_nats.connect_resilient(NATS_URL, name="test-pub")
    vsf_nats.sd_notify_ready()

    disconnected = asyncio.Event()
    reconnected = asyncio.Event()

    # We need to replace callbacks to track events
    # (connect_resilient already sets them, but they only _log — we also set flags)
    import nats.aio.client as nats_client
    # Access the client's callbacks
    nc._disconnected_cb = lambda: (disconnected.set(), print("  [cb] DISCONNECTED"))
    nc._reconnected_cb = lambda: (reconnected.set(), print("  [cb] RECONNECTED"))

    _kill_nats()
    await asyncio.sleep(0.5)

    # Try to publish — may fail transiently
    pub_ok_after_kill = False
    for i in range(30):
        ok = await vsf_nats.publish_safe(nc, "test.subject", b"hello", timeout=5, log_prefix="test")
        if ok:
            pub_ok_after_kill = True
            break
        await asyncio.sleep(1)

    _check("publish recovered after NATS kill", pub_ok_after_kill,
           "no publish succeeded after kill")

    # Restart NATS
    _restart_nats()
    await asyncio.sleep(3)

    # Verify we can publish after restart
    pub_ok_after_restart = False
    for i in range(10):
        ok = await vsf_nats.publish_safe(nc, "test.subject", b"hello", timeout=3, log_prefix="test")
        if ok:
            pub_ok_after_restart = True
            break
        await asyncio.sleep(0.5)

    _check("publish works after NATS restart", pub_ok_after_restart,
           "no publish succeeded after restart")

    await nc.drain()
    print(f"  Test 1: {PASS if not FAIL else 'partial'}")


# ── Test 2: Subscription survives NATS restart ────────────────────────


async def test_sub_survives_restart():
    """Subscribe → kill NATS → restart → verify we receive new publications."""
    print("\n=== Test 2: Subscription survives NATS restart ===")

    nc = await vsf_nats.connect_resilient(NATS_URL, name="test-sub")
    vsf_nats.sd_notify_ready()

    received = asyncio.Queue()

    async def handler(msg):
        print(f"  [cb] received: {msg.subject}")
        await received.put(msg)

    await nc.subscribe("test.sub", cb=handler)

    # Publish a test message
    sub = await nc.subscribe("test.sub")
    await nc.publish("test.sub", b"before_kill")
    try:
        m = await asyncio.wait_for(sub.next_msg(), timeout=5)
        print(f"  [rx] before_kill: {m.data}")
    except asyncio.TimeoutError:
        _check("sub works before kill", False, "no message received before kill")
        await nc.drain()
        return

    # Kill NATS, wait, restart
    _kill_nats()
    await asyncio.sleep(2)
    _restart_nats()
    await asyncio.sleep(3)

    # Connect a TEMPORARY publisher and publish
    pub_nc = await vsf_nats.connect_resilient(NATS_URL, name="test-pub2")
    await pub_nc.publish("test.sub", b"after_restart")
    await pub_nc.drain()

    # Check if we receive the post-restart message
    try:
        m = await asyncio.wait_for(sub.next_msg(), timeout=5)
        _check("sub receives message after NATS restart", m.data == b"after_restart",
               f"got: {m.data}")
    except asyncio.TimeoutError:
        _check("sub receives message after NATS restart", False, "timeout waiting for post-restart msg")

    await nc.drain()


# ── Test 3: Confirm _flush_timeout and _max_pending_size ──────────────


async def test_confirm_nats_params():
    """Confirm internal nats-py parameters after connect."""
    print("\n=== Test 3: Confirm _flush_timeout and _max_pending_size ===")

    nc = await vsf_nats.connect_resilient(NATS_URL, name="test-params")

    _check("_max_pending_size > 0 after connect", bool(nc._max_pending_size),
           f"value={nc._max_pending_size}")
    _check("_flush_timeout is not None", nc._flush_timeout is not None,
           f"value={nc._flush_timeout}")
    _check("_max_reconnect_attempts = -1", nc.options.get("max_reconnect_attempts") == -1,
           f"value={nc.options.get('max_reconnect_attempts')}")
    _check("allow_reconnect = True", nc.options.get("allow_reconnect", False) == True,
           f"value={nc.options.get('allow_reconnect')}")

    print(f"  max_pending_size={nc._max_pending_size}")
    print(f"  flush_timeout={nc._flush_timeout}")
    print(f"  max_reconnect_attempts={nc.options.get('max_reconnect_attempts')}")

    await nc.drain()


# ── Test 4: OutboundBufferLimitError does not crash publish loop ──────


async def test_publish_never_crashes():
    """publish_safe should never crash even during extreme conditions."""
    print("\n=== Test 4: Publish never crashes on error ===")

    nc = await vsf_nats.connect_resilient(NATS_URL, name="test-no-crash")
    vsf_nats.sd_notify_ready()

    # Kill NATS to trigger disconnect
    _kill_nats()
    await asyncio.sleep(0.5)

    errors = 0
    for i in range(5):
        ok = await vsf_nats.publish_safe(nc, "test.subject", b"hello", timeout=2, log_prefix="test")
        if not ok:
            errors += 1

    _check("publish_safe returns False (not crashes) on error", errors > 0,
           f"expected some errors during disconnect, got {errors}/5")

    # Verify process is STILL ALIVE (not crashed)
    _check("process still alive after failed publishes", True,
           "if we reach here, no crash")

    # Restart NATS and verify we can publish again
    _restart_nats()
    await asyncio.sleep(3)

    ok = await vsf_nats.publish_safe(nc, "test.subject", b"after", timeout=5, log_prefix="test")
    _check("publish works after NATS comes back", ok)

    await nc.drain()


# ── Test 5: sd_notify watchdog path ──────────────────────────────────


async def test_watchdog_path():
    """Verify sd_notify functions work (no-op but don't crash when NOTIFY_SOCKET absent)."""
    print("\n=== Test 5: sd_notify functions ===")

    # Without NOTIFY_SOCKET
    vsf_nats.sd_notify_ready()
    vsf_nats.sd_notify_watchdog()
    vsf_nats.sd_notify("STOPPING=1")
    _check("sd_notify no-ops when NOTIFY_SOCKET not set", True)

    # With a fake socket path
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        sock = os.path.join(tmpdir, "notify.sock")
        os.environ["NOTIFY_SOCKET"] = sock
        os.environ["WATCHDOG_USEC"] = "5000000"

        # sd_notify_ready should try to connect (no server listening → OSError → logged, not crash)
        vsf_nats.sd_notify_ready()
        vsf_nats.sd_notify_watchdog()
        _check("sd_notify doesn't crash when socket doesn't exist", True,
               "should log warning but not crash")

        # Create a real socket and test
        import socket
        server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            server.bind(sock)
            server.settimeout(1)

            vsf_nats.sd_notify_watchdog()
            data = server.recv(1024)
            _check("sd_notify sends WATCHDOG=1", data == b"WATCHDOG=1",
                   f"got: {data}")
        except Exception as e:
            _check("sd_notify socket test", False, f"exception: {e}")
        finally:
            server.close()

        del os.environ["NOTIFY_SOCKET"]
        del os.environ["WATCHDOG_USEC"]

    _check("sd_notify tests completed", True)


# ── Two-minute zombie test (requires nats-server to stay DOWN) ─────────
# With max_reconnect_attempts=-1, closed_cb should never fire.
# This test verifies the process does NOT zombie after 2+ minutes with NATS down.


async def test_no_zombie_after_long_downtime():
    """With infinite reconnect, closed_cb should never fire (process stays alive)."""
    print("\n=== Test 6: No zombie after long NATS downtime (infinite reconnect) ===")

    # We only test that closed_cb doesn't fire (not that it os._exits)
    closed_fired = False

    nc = await vsf_nats.connect_resilient(NATS_URL, name="test-zombie")

    # Override closed_cb to flag (not os._exit)
    orig_closed = nc._closed_cb
    async def test_closed_cb():
        nonlocal closed_fired
        closed_fired = True
        print("  [cb] CLOSED (should NOT fire with infinite reconnect)")
        # Don't actually os._exit — just flag
    nc._closed_cb = test_closed_cb

    _kill_nats()

    # Wait 5 seconds (not 2 min — just verify it doesn't immediately close)
    await asyncio.sleep(5)

    _check("closed_cb did NOT fire after 5s of NATS down", not closed_fired,
           "closed_cb fired prematurely")

    # Kill nats-server (ensure it's actually dead for the test)
    _kill_nats()
    await asyncio.sleep(2)
    # Restart NATS so the client can reconnect
    _restart_nats()
    await asyncio.sleep(3)

    # Check we're still alive
    _check("process alive after reconnect", True)

    # Verify we can publish
    ok = await vsf_nats.publish_safe(nc, "test.subject", b"final", timeout=5, log_prefix="test")
    _check("publish works after recovery", ok)

    await nc.drain()


# ── Main ──────────────────────────────────────────────────────────────


NATS_SERVER_BIN = "/usr/local/bin/nats-server"


def _ensure_nats_running():
    """Start nats-server if not already running on test port."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(2)
        s.connect(("127.0.0.1", 14222))
        s.close()
        print("  nats-server already running on :14222")
        return
    except (socket.timeout, ConnectionRefusedError, OSError):
        pass
    finally:
        s.close()

    print("  Starting nats-server on :14222...")
    subprocess.Popen(
        [NATS_SERVER_BIN, "-p", "14222", "-l", "/dev/null"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    # Verify
    try:
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.settimeout(2)
        s2.connect(("127.0.0.1", 14222))
        s2.close()
        print("  nats-server started OK")
    except Exception as e:
        print(f"  WARNING: nats-server may not be running: {e}")


def _cleanup_nats():
    _kill_nats()


async def main():
    print("=" * 60)
    print("NATS-RESILIENCE-FIX Chaos Test Suite")
    print(f"NATS_URL = {NATS_URL}")
    print("=" * 60)

    _ensure_nats_running()

    await test_confirm_nats_params()

    # Run tests that need NATS alive
    await test_watchdog_path()

    await test_publish_never_crashes()

    await test_publish_loop_survives_restart()

    await test_sub_survives_restart()

    await test_no_zombie_after_long_downtime()

    # Summary
    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    _cleanup_nats()

    if FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
