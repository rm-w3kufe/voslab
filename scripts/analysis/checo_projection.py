#!/usr/bin/env python3
"""
checo_projection.py — CHECO CH.b Deterministic Projection Engine
CHECO-PROJ-1 / scripts/checo_projection.py

Reads s3star kpi.db, runs OLS linear trend over last N_WINDOW rows, computes
time-to-breach for each viability dimension, writes projection_report.vsm.

Usage:
  python3 checo_projection.py [--db <path>] [--out <path>] [--window <rows>] [--dry-run]

Calibration caveat (Phase A baseline 2026-06-18):
  stasis_cos and trust series are STATIONARY (slope≈0 at baseline).
  At nominal operating point, all TTBs will be "stable". This is CORRECT —
  the model projects breach only when real drift exists (Phase B perturbation data).
"""
import sqlite3, sys, os, json, argparse
from datetime import datetime, timezone


def parse_ts(ts):
    """kpi.ts_poll → epoch seconds (float). Handles ISO-8601 strings and numerics."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None

# ── Thresholds from norm.vsm norm(vsf-alpha-R1) ─────────────────────────────
THRESHOLDS = {
    "stasis_cos": {"warn": 0.80, "critical": 0.70},
    "trust":      {"warn": 0.80, "critical": None},
}

# Calibrated 2026-06-22 (C2 baseline): noise floor ≈ 0.00028/h (trust).
# Slopes shallower than this threshold are measurement noise, not real drift.
MIN_ACTIONABLE_SLOPE_PER_H = 0.001

# ── OLS: y = a + b*x; returns (slope_per_hour, intercept, r_squared) ────────
def ols(xs, ys):
    n = len(xs)
    if n < 3:
        return None, None, None
    mx = sum(xs) / n
    my = sum(ys) / n
    ss_xx = sum((x - mx)**2 for x in xs)
    ss_yy = sum((y - my)**2 for y in ys)
    ss_xy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if ss_xx < 1e-20:
        return 0.0, my, 0.0
    slope = ss_xy / ss_xx
    intercept = my - slope * mx
    r2 = (ss_xy**2 / (ss_xx * ss_yy)) if ss_yy > 1e-20 else 1.0
    return slope, intercept, r2


def time_to_breach(current, slope_per_h, threshold):
    """
    Returns: ("stable", None) | ("breach", 0) | ("ttb", hours)
    """
    if threshold is None:
        return "stable", None
    if current <= threshold:
        return "breach", 0.0
    if slope_per_h >= -MIN_ACTIONABLE_SLOPE_PER_H:
        return "stable", None
    hours = (current - threshold) / abs(slope_per_h)
    return "ttb", round(hours, 2)


def status_for(stasis_state, stasis_h, trust_state, trust_h):
    if "breach" in (stasis_state, trust_state):
        return "critical"
    # warn if TTB < 12h or already at warn
    warn_ttb = 12.0
    stasis_warn = stasis_state == "ttb" and stasis_h <= warn_ttb
    trust_warn  = trust_state  == "ttb" and trust_h  is not None and trust_h <= warn_ttb
    if stasis_warn or trust_warn:
        return "warn"
    return "nominal"


def load_kpis(db_path, window_rows):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()

    # Discover available columns
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]

    # Try common kpi table names
    table = None
    for candidate in ("kpi_snapshots", "kpi", "snapshots", "s3star_kpi"):
        if candidate in tables:
            table = candidate
            break
    if table is None:
        conn.close()
        raise RuntimeError(f"No known kpi table found in {db_path}. Tables: {tables}")

    cur.execute(f"PRAGMA table_info({table})")
    cols = {r[1] for r in cur.fetchall()}

    # Build SELECT for available fields
    available = []
    for field in ("ts_poll", "stasis_cos", "trust", "regime", "viable"):
        if field in cols:
            available.append(field)
    if "ts_poll" not in available:
        # Try timestamp alternatives
        for alt in ("ts", "timestamp", "created_at"):
            if alt in cols:
                available[0] = alt
                break

    fields = ", ".join(available)
    cur.execute(f"SELECT {fields} FROM {table} ORDER BY ts_poll DESC LIMIT {window_rows}")
    rows = cur.fetchall()
    conn.close()

    # Reverse to chronological order
    rows.reverse()
    return rows, available


def build_report(rows, cols, window_rows, now_iso):
    if not rows:
        return None, "no data"

    # Parse into column dict
    data = {c: [] for c in cols}
    for row in rows:
        for i, c in enumerate(cols):
            data[c].append(row[i])

    # Convert ts_poll to hours-since-start for OLS
    ts_raw = data.get("ts_poll", [])
    if not ts_raw:
        return None, "no ts_poll"

    # DEBT-CHECO-01 fix: ts_poll is ISO-8601 string, not numeric epoch.
    t0 = parse_ts(ts_raw[0])
    ts_h = [(parse_ts(t) - t0) / 3600.0 for t in ts_raw]

    report = {
        "generated_at": now_iso,
        "window_rows":  len(rows),
        "window_hours": round(ts_h[-1] - ts_h[0], 2) if len(ts_h) > 1 else 0,
        "dimensions":   {},
    }

    # ── stasis_cos ───────────────────────────────────────────────────────────
    if "stasis_cos" in data and data["stasis_cos"]:
        ys = data["stasis_cos"]
        current = ys[-1]
        slope, intercept, r2 = ols(ts_h, ys)
        slope_h = slope if slope is not None else 0.0

        ttb_warn_s, ttb_warn_h = time_to_breach(current, slope_h, THRESHOLDS["stasis_cos"]["warn"])
        ttb_crit_s, ttb_crit_h = time_to_breach(current, slope_h, THRESHOLDS["stasis_cos"]["critical"])

        report["dimensions"]["stasis_cos"] = {
            "current":          round(current, 6),
            "slope_per_h":      round(slope_h, 8) if slope_h else 0,
            "r_squared":        round(r2, 4) if r2 is not None else None,
            "warn_threshold":   THRESHOLDS["stasis_cos"]["warn"],
            "critical_threshold": THRESHOLDS["stasis_cos"]["critical"],
            "ttb_warn_state":   ttb_warn_s,
            "ttb_warn_h":       ttb_warn_h,
            "ttb_critical_state": ttb_crit_s,
            "ttb_critical_h":   ttb_crit_h,
        }

    # ── trust ─────────────────────────────────────────────────────────────────
    if "trust" in data and data["trust"]:
        ys = data["trust"]
        current = ys[-1]
        slope, intercept, r2 = ols(ts_h, ys)
        slope_h = slope if slope is not None else 0.0

        ttb_warn_s, ttb_warn_h = time_to_breach(current, slope_h, THRESHOLDS["trust"]["warn"])

        report["dimensions"]["trust"] = {
            "current":        round(current, 6),
            "slope_per_h":    round(slope_h, 8) if slope_h else 0,
            "r_squared":      round(r2, 4) if r2 is not None else None,
            "warn_threshold": THRESHOLDS["trust"]["warn"],
            "ttb_warn_state": ttb_warn_s,
            "ttb_warn_h":     ttb_warn_h,
        }

    # ── regime + viable ───────────────────────────────────────────────────────
    if "regime" in data and data["regime"]:
        report["dimensions"]["regime_current"] = data["regime"][-1]
    if "viable" in data and data["viable"]:
        report["dimensions"]["viable_current"] = bool(data["viable"][-1])

    # ── overall status ────────────────────────────────────────────────────────
    sc = report["dimensions"].get("stasis_cos", {})
    tr = report["dimensions"].get("trust", {})
    status = status_for(
        sc.get("ttb_warn_state", "stable"), sc.get("ttb_warn_h"),
        tr.get("ttb_warn_state", "stable"), tr.get("ttb_warn_h"),
    )
    report["status"] = status

    # ── action hint ───────────────────────────────────────────────────────────
    if status == "critical":
        report["action_hint"] = "ALGEDONIC — dimension in breach; S5 review required"
    elif status == "warn":
        parts = []
        sc_h = sc.get("ttb_warn_h")
        tr_h = tr.get("ttb_warn_h")
        if sc_h and sc.get("ttb_warn_state") == "ttb":
            parts.append(f"stasis_cos breach in {sc_h:.1f}h")
        if tr_h and tr.get("ttb_warn_state") == "ttb":
            parts.append(f"trust breach in {tr_h:.1f}h")
        report["action_hint"] = "WARN: " + "; ".join(parts)
    else:
        sc_curr = sc.get("current", "?")
        tr_curr = tr.get("current", "?")
        report["action_hint"] = (
            f"NOMINAL — stasis_cos={sc_curr} trust={tr_curr}; "
            "all dimensions within bounds, no projected breach"
        )

    return report, None


def write_vsm(report, out_path):
    def fmt_val(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, float):
            return f"{v}"
        if isinstance(v, str):
            return f'"{v}"'
        return str(v)

    lines = [
        "@vsm 1.2.1",
        f"// projection_report — CHECO-PROJ-1 / {report['generated_at']}",
        "",
        "projection_report {",
        f'  generated_at    = "{report["generated_at"]}"',
        f'  window_rows     = {report["window_rows"]}',
        f'  window_hours    = {report["window_hours"]}',
        f'  status          = "{report["status"]}"',
        f'  action_hint     = "{report["action_hint"]}"',
        "",
        "  dimensions {",
    ]

    sc = report["dimensions"].get("stasis_cos", {})
    if sc:
        lines += [
            "    stasis_cos {",
            f'      current                 = {fmt_val(sc.get("current"))}',
            f'      slope_per_h             = {fmt_val(sc.get("slope_per_h"))}',
            f'      r_squared               = {fmt_val(sc.get("r_squared"))}',
            f'      ttb_warn_state          = "{sc.get("ttb_warn_state", "stable")}"',
            f'      ttb_warn_h              = {fmt_val(sc.get("ttb_warn_h"))}',
            f'      ttb_critical_state      = "{sc.get("ttb_critical_state", "stable")}"',
            f'      ttb_critical_h          = {fmt_val(sc.get("ttb_critical_h"))}',
            "    }",
        ]

    tr = report["dimensions"].get("trust", {})
    if tr:
        lines += [
            "    trust {",
            f'      current                 = {fmt_val(tr.get("current"))}',
            f'      slope_per_h             = {fmt_val(tr.get("slope_per_h"))}',
            f'      r_squared               = {fmt_val(tr.get("r_squared"))}',
            f'      ttb_warn_state          = "{tr.get("ttb_warn_state", "stable")}"',
            f'      ttb_warn_h              = {fmt_val(tr.get("ttb_warn_h"))}',
            "    }",
        ]

    regime = report["dimensions"].get("regime_current")
    viable = report["dimensions"].get("viable_current")
    if regime is not None:
        lines.append(f'    regime_current          = "{regime}"')
    if viable is not None:
        lines.append(f'    viable_current          = {fmt_val(viable)}')

    lines += ["  }", "}"]
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db",     default="/var/lib/vsf/s3_star/kpi.db",
                    help="Path to s3star kpi.db (read-only)")
    ap.add_argument("--out",    default=os.path.expanduser("~/.vsf/projections/projection_report.vsm"),
                    help="Output .vsm path")
    ap.add_argument("--window", type=int, default=144,
                    help="Number of kpi rows to use (~24h at 10-min sampling)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print report to stdout, do not write file")
    ap.add_argument("--json",   action="store_true",
                    help="Also write <out>.json alongside the vsm")
    args = ap.parse_args()

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not os.path.exists(args.db):
        print(f"ERROR: kpi.db not found at {args.db}", file=sys.stderr)
        sys.exit(1)

    rows, cols = load_kpis(args.db, args.window)
    report, err = build_report(rows, cols, args.window, now_iso)

    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print(json.dumps(report, indent=2))
        return

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    write_vsm(report, args.out)
    print(f"[{now_iso}] CHECO-PROJ-1 | status={report['status']} | {report['action_hint']}")
    print(f"  → {args.out}")

    if args.json:
        json_path = args.out.replace(".vsm", ".json")
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"  → {json_path}")


if __name__ == "__main__":
    main()
