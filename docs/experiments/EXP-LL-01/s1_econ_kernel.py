#!/usr/bin/env python3
"""
s1_econ_kernel.py — EXP-LL-01 live S1 kernel (socioeconomic domain, LXC 113 s1-econ).
ref: docs/experiments/EXP-LL-01/spec.vsm  · sibling: the climate kernel on LXC 112

A live viable-system kernel for a Chile-shaped open economy. Each tick it runs the
Lange-Lerner tâtonnement toward market clearing and emits a φ↑ event on NATS, mirroring
the climate S1's vsf.clima.* pattern so S3 (the resource bargain, ITEM_20) and the opsroom
consume it uniformly.

Economic viability signal (the φ↑ stasis_cos):
    stasis_cos = exp(−‖z(p)‖)         z = excess demand (shortage/surplus)
  markets clear (z→0) → stasis≈1 (viable) ; disequilibrium/shortage → stasis→0 (stressed).
When the international gravitating force (copper demand from China) shocks the economy, the
tâtonnement cannot clear in time → stasis drops → S3 should grant s1-econ more compute.
That IS the load: economic turbulence, the model's own stress signal.

Stdlib only (no nats-py on 113): a minimal NATS publisher over a raw socket.
Real Chile parameters loaded from cache/chile_params.json (fetch_chile.py); falls back
to sane defaults so the kernel runs before data is wired.
"""
import json
import math
import os
import socket
import sys
import time
from datetime import datetime, timezone

import numpy as np

# ── Real copper feed (EXP-LL-01-COPPER) ────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_COPPER_FEED_PATH = os.path.join(_SCRIPT_DIR, "copper_price_feed.py")
if os.path.exists(_COPPER_FEED_PATH):
    import importlib.util
    _spec = importlib.util.spec_from_file_location("copper_price_feed", _COPPER_FEED_PATH)
    _copper_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_copper_mod)
    _HAS_REAL_COPPER = True
else:
    _HAS_REAL_COPPER = False
    _copper_mod = None

NATS_HOST   = os.environ.get("NATS_HOST", "10.10.20.20")
NATS_PORT   = int(os.environ.get("NATS_PORT", "4222"))
TICK_SECS   = int(os.environ.get("TICK_SECS", "60"))
LOG_DIR     = os.environ.get("ECON_LOG_DIR", "/var/log/s1-econ")
PARAMS_PATH = os.environ.get("ECON_PARAMS",
                             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "cache", "chile_params.json"))
EPS = 1e-9

# Chile sectors (goods). The numéraire is the last good (services). Default value-added
# shares (World Bank, ~2022) used only if the data cache is absent.
DEFAULT = {
    "sectors": ["mining", "agriculture", "manufacturing", "services"],
    "shares":  [0.12, 0.04, 0.11, 0.73],   # consumer preference weights ≈ VA shares
    "export_base": [1.0, 0.25, 0.30, 0.05], # mining (copper) dominates exports
    "population_m": 19.6,
}


def _now():
    return datetime.now(timezone.utc).isoformat()


# ── Minimal NATS publisher (stdlib socket) ─────────────────────────────────────────

class NatsPub:
    def __init__(self, host, port):
        self.host, self.port, self.sock = host, port, None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=5)
        self.sock.recv(4096)                                   # server INFO
        self.sock.sendall(b'CONNECT {"verbose":false,"pedantic":false,"name":"s1-econ"}\r\n')
        self.sock.sendall(b'PING\r\n')
        self.sock.recv(64)                                     # PONG
        print(f"[s1-econ] NATS connected {self.host}:{self.port}", flush=True)

    def pub(self, subject, payload: bytes):
        if self.sock is None:
            self.connect()
        msg = b"PUB " + subject.encode() + b" " + str(len(payload)).encode() + b"\r\n" + payload + b"\r\n"
        try:
            self.sock.sendall(msg)
        except OSError:
            self.sock = None                                   # force reconnect next pub
            self.connect()
            self.sock.sendall(msg)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None


# ── The economy ────────────────────────────────────────────────────────────────────

def load_params():
    try:
        with open(PARAMS_PATH) as f:
            p = json.load(f)
        print(f"[s1-econ] loaded real Chile params from {PARAMS_PATH}", flush=True)
        return p
    except Exception:
        print(f"[s1-econ] params cache absent → DEFAULT (run fetch_chile.py to wire real data)", flush=True)
        return DEFAULT


class ChileEconomy:
    """Cobb-Douglas domestic demand + exogenous export demand on the mining good,
    scaled by the international 'copper force' (China demand). Tâtonnement in numéraire."""

    def __init__(self, params):
        self.sectors = params["sectors"]
        self.n = len(self.sectors)
        self.alpha = np.array(params["shares"], float)
        self.alpha /= self.alpha.sum()
        self.export_base = np.array(params["export_base"], float)
        self.supply = np.ones(self.n)                          # normalized productive capacity
        self.q = np.ones(self.n - 1)                           # prices (numéraire = last good)
        self.t = 0

    def copper_force(self):
        """International gravitating force: copper/China demand.
        v1 = slow cycle + noise (synthetic).
        v2 (EXP-LL-01-COPPER) = real copper price feed (Yahoo Finance HG=F),
        normalized by 12-month mean. Falls back to synthetic on fetch failure."""
        if _HAS_REAL_COPPER and _copper_mod is not None:
            try:
                result = _copper_mod.get_copper_force()
                cf = result.get("copper_force", 1.0)
                # Add small noise so the signal isn't pure constant between monthly prints
                shock = float(np.random.default_rng(self.t).normal(0, 0.02))
                return max(0.1, cf + shock)
            except Exception as e:
                print(f"[s1-econ] copper feed failed: {e}; using synthetic", flush=True)
        base = 1.0 + 0.30 * math.sin(self.t / 12.0)
        shock = float(np.random.default_rng(self.t).normal(0, 0.08))
        return max(0.1, base + shock)

    def excess_demand(self, q):
        p = np.concatenate([np.maximum(q, EPS), [1.0]])
        wealth = float(np.sum(self.supply * p))               # endowment-valued income
        domestic = self.alpha * wealth / p                    # Cobb-Douglas demand
        exports = self.export_base.copy()
        exports[0] *= self.copper_force()                     # copper export demand (China)
        z = domestic + 0.15 * exports - self.supply
        return z

    def step(self, k=0.15):
        """One tâtonnement adjustment (numéraire goods only)."""
        z = self.excess_demand(self.q)
        self.q = np.maximum(self.q + k * z[:-1], EPS)
        return z

    def tick(self):
        self.t += 1
        for _ in range(8):                                    # a few adjustment rounds per tick
            z = self.step()
        zr = z[:-1]
        znorm = float(np.linalg.norm(zr))
        stasis = math.exp(-znorm)                             # ∈ (0,1]; 1 = markets clear
        p = np.concatenate([self.q, [1.0]])
        return {
            "stasis_cos": stasis, "excess_demand_norm": znorm,
            "prices": p.tolist(), "excess_demand": z.tolist(),
            "copper_force": self.copper_force(),
        }


def regime(stasis):
    if stasis >= 0.80:
        return "clearing"
    if stasis >= 0.55:
        return "adjusting"
    if stasis >= 0.35:
        return "stressed"
    return "crisis"


# ── Main loop ────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    econ = ChileEconomy(load_params())
    nats = NatsPub(NATS_HOST, NATS_PORT)
    try:
        nats.connect()
    except Exception as e:
        print(f"[s1-econ] NATS connect failed ({e}); will retry on first pub", flush=True)

    print(f"[s1-econ] live — {econ.n} sectors {econ.sectors}, tick={TICK_SECS}s", flush=True)
    while True:
        m = econ.tick()
        st = m["stasis_cos"]
        snap = {s: {"price": round(m["prices"][i], 4),
                    "excess_demand": round(m["excess_demand"][i], 4)}
                for i, s in enumerate(econ.sectors)}
        evt = {
            "ts": _now(), "source_id": "s1-econ", "system_id": "chile-economy",
            "vsm_level": 1, "event_type": "system_aggregate",
            "regime": regime(st), "confidence": round(min(1.0, 1.0 - m["excess_demand_norm"] / 5), 3),
            "n_sectors": econ.n,
            "stasis_cos": round(st, 4), "stasis_cos_sys": round(st, 4),
            "excess_demand_norm": round(m["excess_demand_norm"], 4),
            "copper_force": round(m["copper_force"], 4),
            "sector_snapshot": snap,
        }
        payload = json.dumps(evt).encode()
        # system-level φ↑ (what S3 acts on) + per-sector φ↑ (zone analog)
        try:
            nats.pub("vsf.econ.chile.phi_up", payload)
            for s in econ.sectors:
                sev = {"ts": evt["ts"], "source_id": "s1-econ", "sector": s, "vsm_level": 2,
                       "event_type": "sector_aggregate", **snap[s]}
                nats.pub(f"vsf.econ.{s}.phi_up", json.dumps(sev).encode())
            published = True
        except Exception as e:
            published = False
            print(f"[s1-econ] pub failed: {e}", flush=True)

        with open(os.path.join(LOG_DIR, "phi_up.jsonl"), "a") as f:
            f.write(payload.decode() + "\n")
        print(f"[s1-econ] t={econ.t} stasis={st:.3f} regime={evt['regime']} "
              f"copper_force={m['copper_force']:.2f} pub={'ok' if published else 'FAIL'}", flush=True)
        time.sleep(TICK_SECS)


if __name__ == "__main__":
    sys.exit(main())
