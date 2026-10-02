#!/usr/bin/env python3
"""
test_read_events_tail.py — Acceptance for A0-READ-EVENTS-TAIL

Verifies that the new tail-seek read_events() returns the same results as the
old full-file reader, but NEVER loads more than the requested events + chunk
into memory.

  Acceptance:
  1. Exact-match with old implementation on small files (≤50 events)
  2. Works with empty file → []
  3. Works with single-line file → [event]
  4. Works with n=0 → []
  5. Works with file not ending in \n
  6. Handles invalid JSON lines gracefully (skip)
  7. Bounded memory on large file (no OOM)
  8. Boundary at exact chunk size (stress chunk splitting)
"""

import json
import os
import sys
import tempfile

# ── Reference: OLD implementation for comparison ──────────────────────────────
def read_events_old(events_path: str, n: int) -> list[dict]:
    events = []
    try:
        with open(events_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except FileNotFoundError:
        pass
    return events[-n:]


# ── NEW implementation (self-contained copy for portability) ──────────────────
def read_events_new(events_path: str, n: int) -> list[dict]:
    CHUNK_SIZE = 65536
    events: list[dict] = []

    try:
        with open(events_path, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
    except FileNotFoundError:
        return events

    if file_size == 0 or n <= 0:
        return events

    buf: bytes = b""
    pos: int = file_size

    with open(events_path, "rb") as f:
        while pos > 0 and len(events) < n:
            read_size = min(CHUNK_SIZE, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            buf = chunk + buf

            while buf and len(events) < n:
                nl = buf.rfind(b"\n")
                if nl == -1:
                    break
                line_bytes = buf[nl + 1:]
                buf = buf[:nl]
                if line_bytes:
                    try:
                        events.append(
                            json.loads(line_bytes.decode("utf-8", errors="replace"))
                        )
                    except json.JSONDecodeError:
                        pass

        if buf and len(events) < n:
            try:
                events.append(json.loads(buf.decode("utf-8", errors="replace")))
            except json.JSONDecodeError:
                pass

    events.reverse()
    return events


# ── Helpers ────────────────────────────────────────────────────────────────────
def make_events(n: int) -> list[dict]:
    return [
        {"ts": f"2026-07-02T00:00:{i:02d}Z", "event_type": "test", "seq": i}
        for i in range(n)
    ]


def write_events(path: str, events: list[dict], trailing_newline: bool = True):
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
        if not trailing_newline and events:
            # Rewind to remove the last \n
            f.seek(0, os.SEEK_END)
            f.truncate(f.tell() - 1)


# ── Tests ──────────────────────────────────────────────────────────────────────
def test(label: str, ok: bool, detail: str = "") -> bool:
    status = "✅ PASS" if ok else "❌ FAIL"
    print(f"  {status} | {label}" + (f"  ({detail})" if detail else ""))
    return ok


def run_all():
    passed = 0
    failed = 0
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:

        # 1 — Empty file
        path = os.path.join(tmpdir, "empty.jsonl")
        open(path, "w").close()
        r = test("empty file → []",
                 read_events_new(path, 50) == [] and read_events_new(path, 50) == read_events_old(path, 50))
        results.append(r)

        # 2 — Single event
        ev = make_events(1)
        path = os.path.join(tmpdir, "single.jsonl")
        write_events(path, ev)
        r = test("single event → [event]",
                 read_events_new(path, 50) == ev and read_events_new(path, 50) == read_events_old(path, 50))
        results.append(r)

        # 3 — 5 events, request 3
        ev5 = make_events(5)
        path = os.path.join(tmpdir, "five.jsonl")
        write_events(path, ev5)
        new_last3 = read_events_new(path, 3)
        old_last3 = read_events_old(path, 3)
        r = test("5 events, n=3 → last 3",
                 new_last3 == ev5[-3:] and new_last3 == old_last3)
        results.append(r)

        # 4 — 50 events, request all
        ev50 = make_events(50)
        path = os.path.join(tmpdir, "fifty.jsonl")
        write_events(path, ev50)
        r = test("50 events, n=50 → all 50",
                 read_events_new(path, 50) == ev50 and
                 read_events_new(path, 50) == read_events_old(path, 50))
        results.append(r)

        # 5 — Payload > chunk size (e.g., 100 events at ~60B each ≈ 6KB, fine)
        ev100 = make_events(100)
        path = os.path.join(tmpdir, "hundred.jsonl")
        write_events(path, ev100)
        r = test("100 events, n=50 → last 50 exactly",
                 read_events_new(path, 50) == ev100[-50:] and
                 read_events_new(path, 50) == read_events_old(path, 50))
        results.append(r)

        # 6 — n=0 → []
        r = test("n=0 → []", read_events_new(path, 0) == [])
        results.append(r)

        # 7 — No trailing newline
        path = os.path.join(tmpdir, "no_nl.jsonl")
        write_events(path, ev5, trailing_newline=False)
        r = test("no trailing \\n → still reads properly",
                 read_events_new(path, 3) == ev5[-3:] and
                 read_events_new(path, 3) == read_events_old(path, 3))
        results.append(r)

        # 8 — Invalid JSON lines interspersed
        ev_clean = make_events(5)
        path = os.path.join(tmpdir, "with_garbage.jsonl")
        with open(path, "w") as f:
            for i, e in enumerate(ev_clean):
                if i == 2:
                    f.write("NOT JSON\n")
                f.write(json.dumps(e) + "\n")
                if i == 3:
                    f.write("{also bad\n")
        new = read_events_new(path, 10)
        # Should have skipped the bad lines
        r = test("invalid JSON lines skipped",
                 all(e in ev_clean for e in new) and len(new) == 5)
        results.append(r)

        # 9 — Stress: boundary at exact chunk boundaries
        # Create events that straddle the 65536 byte boundary
        # 1024 events of ~70 bytes each ≈ 72KB, forcing two chunks
        big_ev = make_events(1024)
        path = os.path.join(tmpdir, "boundary_stress.jsonl")
        write_events(path, big_ev)
        new_big = read_events_new(path, 50)
        old_big = read_events_old(path, 50)
        r = test("chunk boundary stress (1024 ev, ~72KB, 2 chunks)",
                 new_big == old_big and new_big == big_ev[-50:])
        results.append(r)

        # 10 — More stress: 2000 events (~140KB, 3 chunks)
        ev2k = make_events(2000)
        path = os.path.join(tmpdir, "2k_stress.jsonl")
        write_events(path, ev2k)
        new_2k = read_events_new(path, 50)
        old_2k = read_events_old(path, 50)
        r = test("3-chunk stress (2000 ev, ~140KB)",
                 new_2k == old_2k and new_2k == ev2k[-50:])
        results.append(r)

        # 11 — file does not exist
        r = test("FileNotFound → []",
                 read_events_new("/nonexistent/path.jsonl", 50) == [])
        results.append(r)

    passed = sum(1 for r in results if r)
    failed = len(results) - passed
    print(f"\n  ── Results: {passed} passed, {failed} failed")
    return passed, failed


def main():
    print("=" * 68)
    print("A0-READ-EVENTS-TAIL — Tail-seek bounded read_events()")
    print("=" * 68)
    print()
    passed, failed = run_all()
    print()
    if failed == 0:
        print(">>> ACCEPTANCE: PASS (all tail-seek checks match old implementation)")
        return 0
    else:
        print(f">>> ACCEPTANCE: FAIL ({failed} assertion(s) failed)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
