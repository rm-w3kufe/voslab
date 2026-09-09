#!/usr/bin/env python3
"""
chain_verifier.py — W1-CHAIN-SCAN: full canonical chain integrity verifier.

Reads every event in events.jsonl, recomputes prev_hash references, classifies
all integrity failures by the fork-event taxonomy (AC-M3):
  - diverge_origin: event where prev_hash ≠ actual_prev_hash from prior event
  - resume_wrong:   chain restart after reset where first event's prev_hash ≠ last event's hash
  - epoch_rollback: monotonically decreasing event sequence number
  - truncated_line: line ends without newline or is partial JSON (write race / crash)
  - content_tamper: stored hash ≠ SHA256(event_without_hash)

UPDATED: Now uses socratic engine for classification via chain_classify.tree.vsm
Predicates: is_content_tamper, is_diverge_origin, is_resume_wrong,
            is_epoch_rollback, is_truncated_line

Usage:
  python3 chain_verifier.py <events.jsonl> [--output <report.json>]
  python3 chain_verifier.py --check <events.jsonl> <event_id>  # quick check one
"""

import json
import sys
import os
import hashlib
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Add classifier path for socratic engine
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vsl" / "classifier"))
from vsf_socratic_engine import _create_engine, _ROOT

# Load tree
TREE = _ROOT / ".opencode/plugins/support/trees/chain_classify.tree.vsm"


def compute_event_hash(event: dict) -> str:
    """Compute SHA256 of event with hash field removed (canonical form)."""
    ev = {k: v for k, v in event.items() if k != "hash"}
    canonical = json.dumps(ev, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class ChainVerifier:
    def __init__(self, events_path: str):
        self.path = events_path
        self.total = 0
        self.truncated = 0
        self.content_tamper = 0
        self.diverge_origin = 0
        self.resume_wrong = 0
        self.epoch_rollback = 0
        self.prev_hash_missing = 0  # event lacks prev_hash field entirely
        self.errors = []  # first 50 errors kept
        self.last_hash = None
        self.last_seq = None
        self.last_event = None
        self.chain_resets = 0  # clean resets (no prev_hash = start of chain segment)

    def classify(self, ev: dict, line_num: int, stored_hash: str, prev_hash: str):
        """Classify integrity failure by taxonomy using socratic engine."""
        err = {
            "line": line_num,
            "event_type": ev.get("event_type", "?"),
            "ts": ev.get("ts", "?"),
        }

        # Build context for socratic engine
        ctx = {
            "event": ev,
            "stored_hash": stored_hash,
            "prev_hash": prev_hash,
            "actual_prev": self.last_hash,
            "algedonic_seq": ev.get("algedonic_seq"),
            "last_algedonic_seq": self.last_seq,
            "is_truncated": False,
            "is_chain_start": prev_hash is not None and prev_hash != "" and self.last_hash is None,
        }

        # Use socratic engine for classification
        engine = _create_engine()
        tree_text = TREE.read_text(encoding="utf-8")
        result = engine.evaluate(tree_text, ctx)
        
        classification = result.home
        
        # Handle classification results
        if classification == "content_tamper":
            self.content_tamper += 1
            recomputed = compute_event_hash(ev)
            err["class"] = "content_tamper"
            err["detail"] = f"stored={stored_hash[:16]}.. ≠ recomputed={recomputed[:16]}.."
            self.errors.append(err)
            return
        
        elif classification == "diverge_origin":
            self.diverge_origin += 1
            if self.last_hash is None:
                err["detail"] = f"first event with prev_hash={prev_hash[:16]}.. — cannot verify"
            else:
                err["detail"] = (f"prev_hash={prev_hash[:16]}.. ≠ actual last hash "
                                 f"{self.last_hash[:16]}..")
            err["class"] = "diverge_origin"
            self.errors.append(err)
        
        elif classification == "resume_wrong":
            self.resume_wrong += 1
            err["class"] = "resume_wrong"
            err["detail"] = f"chain restart with prev_hash={prev_hash[:16]}.. ≠ last hash"
            self.errors.append(err)
        
        elif classification == "epoch_rollback":
            self.epoch_rollback += 1
            err["class"] = "epoch_rollback"
            err["detail"] = f"seq {ev.get('algedonic_seq')} < previous {self.last_seq}"
            self.errors.append(err)
        
        elif classification == "truncated_line":
            self.truncated += 1
            err["class"] = "truncated_line"
            err["detail"] = "line truncated or partial JSON"
            self.errors.append(err)
        
        elif classification == "ok":
            # No error — track chain state
            if prev_hash is None or prev_hash == "":
                self.chain_resets += 1
        
        # Update chain state
        self.last_hash = stored_hash
        self.last_seq = ev.get("algedonic_seq")
        self.last_event = ev

    def run(self, report_path: str = None) -> dict:
        """Full scan of events file. Returns summary dict."""
        start = datetime.now(timezone.utc)
        byte_pos = 0
        file_size = os.path.getsize(self.path)

        with open(self.path, "r", errors="replace") as f:
            for line_num, line in enumerate(f, 1):
                self.total += 1
                if self.total % 50000 == 0:
                    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
                    pct = byte_pos / file_size * 100 if file_size else 0
                    print(f"  ...{self.total:>6} events scanned ({pct:.0f}%, "
                          f"{elapsed:.0f}s)", file=sys.stderr)

                line = line.rstrip("\n")
                byte_pos += len(line) + 1  # +1 for the stripped \n

                # Detect truncated lines
                if not line:
                    self.truncated += 1
                    continue

                try:
                    ev = json.loads(line)
                except json.JSONDecodeError as e:
                    self.truncated += 1
                    if len(self.errors) < 50:
                        self.errors.append({
                            "line": line_num,
                            "class": "truncated_line",
                            "detail": str(e),
                        })
                    continue

                stored_hash = ev.get("hash")
                prev_hash = ev.get("prev_hash")

                self.classify(ev, line_num, stored_hash, prev_hash)

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()

        summary = {
            "scan_ts": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "path": self.path,
            "file_size_bytes": file_size,
            "total_events": self.total,
            "truncated_lines": self.truncated,
            "chain_resets": self.chain_resets,
            "errors": {
                "content_tamper": self.content_tamper,
                "diverge_origin": self.diverge_origin,
                "resume_wrong": self.resume_wrong,
                "epoch_rollback": self.epoch_rollback,
                "prev_hash_missing": self.prev_hash_missing,
                "total_unique": (self.content_tamper + self.diverge_origin +
                                 self.resume_wrong + self.epoch_rollback),
            },
            "elapsed_s": round(elapsed, 1),
            "events_per_sec": round(self.total / elapsed, 1) if elapsed > 0 else 0,
        }

        # Keep first 50 errors in output
        summary["sample_errors"] = self.errors[:50]
        summary["error_count_truncated"] = len(self.errors) > 50
        summary["pct_linear"] = round(
            (self.total - sum(summary["errors"].values())) / self.total * 100, 2
        ) if self.total > 0 else 100.0

        if report_path:
            with open(report_path, "w") as f:
                json.dump(summary, f, indent=2)
            print(f"Report written to {report_path}", file=sys.stderr)

        return summary


def main():
    parser = argparse.ArgumentParser(description="Canonical chain integrity verifier")
    parser.add_argument("events_path", help="Path to events.jsonl")
    parser.add_argument("--output", "-o", help="Write JSON report to path")
    parser.add_argument("--check", type=int, help="Line number to check specifically")
    args = parser.parse_args()

    if args.check:
        # Quick single-event check
        with open(args.events_path, "r", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if i == args.check:
                    ev = json.loads(line)
                    stored = ev.get("hash", "")
                    computed = compute_event_hash(ev)
                    match = stored == computed
                    print(f"Line {args.check}: hash {'✓ MATCH' if match else '✗ MISMATCH'}")
                    print(f"  Stored:   {stored[:32]}.." if stored else "  Stored:   (none)")
                    print(f"  Computed: {computed[:32]}..")
                    print(f"  Event:    {json.dumps(ev, indent=2)[:500]}")
                    return 0 if match else 1
        print(f"Line {args.check} not found")
        return 1

    verifier = ChainVerifier(args.events_path)
    results = verifier.run(report_path=args.output)

    print(f"\n{'='*60}")
    print(f"CHAIN VERIFICATION REPORT")
    print(f"{'='*60}")
    print(f"  Events scanned:    {results['total_events']:>8,}")
    print(f"  File size:         {results['file_size_bytes'] / 1024 / 1024:.0f} MB")
    print(f"  Chain linearity:   {results['pct_linear']}%")
    print(f"  Chain resets:      {results['chain_resets']}")
    print(f"  Truncated lines:   {results['truncated_lines']}")
    print(f"  Total errors:      {results['errors']['total_unique']}")
    print(f"    content_tamper:  {results['errors']['content_tamper']}")
    print(f"    diverge_origin:  {results['errors']['diverge_origin']}")
    print(f"    resume_wrong:    {results['errors']['resume_wrong']}")
    print(f"    epoch_rollback:  {results['errors']['epoch_rollback']}")
    print(f"  Elapsed:           {results['elapsed_s']}s")
    print(f"  Throughput:        {results['events_per_sec']}/s")

    if results["sample_errors"]:
        print(f"\n  First {min(5, len(results['sample_errors']))} errors:")
        for e in results["sample_errors"][:5]:
            print(f"    L{e['line']:>6} [{e['class']}] {e.get('detail','')[:120]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
