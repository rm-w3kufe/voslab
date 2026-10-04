#!/usr/bin/env python3
"""
langelerner.py — EXP-LL-01 reference simulator (numéraire formulation).
ref: docs/experiments/EXP-LL-01/spec.vsm

Lange-Lerner price tâtonnement as a VSM control loop. Numéraire normalization
(pin pₙ=1) removes the homogeneity/Walras degeneracy, so the reduced (n−1)×(n−1)
Jacobian is non-singular and Newton + spectral analysis are well-posed.

Two economies:
  - gross_substitute : Cobb-Douglas exchange economy → globally convergent (easy case)
  - scarf            : Scarf (1960) 3-good Leontief economy → naive tâtonnement does NOT
                       converge (discrete Euler spirals out; continuous flow orbits a centre)

VSM layers (toggleable), each a regulator with more "requisite variety":
  - S3 only : naive tâtonnement   qᵢ ← qᵢ + k·zᵢ(p)            (model-free, reactive)
  - +S2     : anti-oscillation     PD/derivative damping  qᵢ ← qᵢ + k·zᵢ − γ·(qᵢ − qᵢ_prev)
                                    (model-free; removes the energy the orbit gains → spirals in;
                                     γ swept, best reported)
  - +S4     : anticipation         regularised Newton step  q ← q − k·Jr⁻¹·z   (model-based)

Headline (H_LL1): [scarf, S3-only] does NOT converge, but VSM structure (+S2 damping
and/or +S4 model) drives it to equilibrium → VSM structure expands the basin.
Hayek-as-Ashby: the regulator needs more variety than naive price-groping.

Fierro Q2/Q3 (mirrors EXP-S1-CLIMA-01/fierro_q123.py):
  Q2 contraction : AR(1) coeff α on ‖q(t)−q*‖ → λ = log α ; λ<0 ⟺ converges
  Q3 σ_max       : spectral radius of the linearized regulator operator at q*
  Q1 Ω-convex    : DEFERRED to P1 (Doughnut). P0 reports the basin fraction instead.
"""
import json
import os
import numpy as np

EPS_PRICE = 1e-9
EPS_CONV  = 1e-6
STEPS     = 4000
SEED      = 7
rng = np.random.default_rng(SEED)


# ── Economies (full price vector p of length n; Walras' law p·z = 0) ───────────────

def scarf_excess_demand(p):
    """Scarf (1960) symmetric 3-good economy. Equilibrium at p=(1,1,1)."""
    p1, p2, p3 = p
    z1 = -p2 / (p1 + p2) + p3 / (p3 + p1)
    z2 = -p3 / (p2 + p3) + p1 / (p1 + p2)
    z3 = -p1 / (p3 + p1) + p2 / (p2 + p3)
    return np.array([z1, z2, z3])


def make_cobb_douglas(n=3, H=4):
    """Cobb-Douglas exchange economy → gross-substitute excess demand."""
    alpha = rng.dirichlet(np.ones(n), size=H)
    omega = rng.uniform(0.5, 2.0, size=(H, n))
    total_endow = omega.sum(axis=0)

    def excess_demand(p):
        wealth = omega @ p
        demand = (alpha * wealth[:, None] / p[None, :]).sum(axis=0)
        return demand - total_endow

    return excess_demand


# ── Numéraire helpers (state q = p[:-1], with p[-1] ≡ 1) ───────────────────────────

def to_p(q):
    return np.concatenate([np.maximum(q, EPS_PRICE), [1.0]])


def z_reduced(z_fn, q):
    """Excess demand of the non-numéraire goods at q (the goods the CPB actually prices)."""
    return z_fn(to_p(q))[:-1]


def jac_reduced(z_fn, q, h=1e-6):
    m = len(q)
    J = np.zeros((m, m))
    z0 = z_reduced(z_fn, q)
    for j in range(m):
        qq = q.copy()
        qq[j] += h
        J[:, j] = (z_reduced(z_fn, qq) - z0) / h
    return J


def find_equilibrium(z_fn, n, q0=None):
    """Newton on the reduced system z[:-1](q)=0 (non-singular)."""
    q = np.ones(n - 1) if q0 is None else q0.copy()
    for _ in range(200):
        zr = z_reduced(z_fn, q)
        if np.max(np.abs(zr)) < 1e-13:
            break
        J = jac_reduced(z_fn, q)
        dq = np.linalg.solve(J + 1e-10 * np.eye(n - 1), -zr)
        q = np.maximum(q + dq, EPS_PRICE)
    return q


# ── Tâtonnement driver ─────────────────────────────────────────────────────────────

def tatonnement(z_fn, q0, k, n, steps=STEPS, s2=False, s4=False, gamma=0.0):
    q = np.maximum(q0.copy(), EPS_PRICE)
    q_prev = q.copy()
    path, znorm = [], []
    for _ in range(steps):
        zr = z_reduced(z_fn, q)
        znorm.append(float(np.max(np.abs(zr))))
        if not np.all(np.isfinite(q)) or np.max(np.abs(q)) > 1e6:
            break                                   # diverged
        if s4:
            J = jac_reduced(z_fn, q)
            dq = np.linalg.solve(J + 1e-6 * np.eye(n - 1), -zr)
            q_new = q + k * dq
        else:
            step = k * zr
            if s2:                                  # PD / derivative damping (anti-oscillation)
                step = step - gamma * (q - q_prev)
            q_new = q + step
        q_prev = q
        q = np.maximum(q_new, EPS_PRICE)
        path.append(q.copy())
    return {"path": np.array(path), "znorm": np.array(znorm)}


# ── Fierro Q2 / Q3 ──────────────────────────────────────────────────────────────────

def q2_contraction(path, q_star, tail_frac=0.4):
    d = np.linalg.norm(path - q_star[None, :], axis=1)
    d = d[np.isfinite(d)]
    if len(d) < 10:
        return {"alpha": float("inf"), "lambda": float("inf"), "d_final": float("inf")}
    tail = d[int(len(d) * (1 - tail_frac)):]
    tail = tail[tail > 1e-15]
    if len(tail) < 3:
        return {"alpha": 0.0, "lambda": float("-inf"), "d_final": float(d[-1])}
    x, y = tail[:-1], tail[1:]
    alpha = float(np.dot(x, y) / np.dot(x, x)) if np.dot(x, x) > 0 else 1.0
    lam = float(np.log(alpha)) if alpha > 0 else float("-inf")
    return {"alpha": alpha, "lambda": lam, "d_final": float(d[-1])}


def q3_sigma_max(z_fn, q_star, k, n, s2=False, s4=False, gamma=0.0):
    """Spectral radius of the linearised regulator map at q*."""
    J = jac_reduced(z_fn, q_star)
    m = n - 1
    if s4:
        op = np.eye(m) - k * np.linalg.solve(J + 1e-6 * np.eye(m), J)
    elif s2:
        # 2nd-order PD system, augmented state [q, q_prev]:
        # q⁺ = (I + kJ − γI) q + γ q_prev
        A = np.eye(m) + k * J - gamma * np.eye(m)
        op = np.block([[A, gamma * np.eye(m)], [np.eye(m), np.zeros((m, m))]])
    else:
        op = np.eye(m) + k * J
    return float(np.max(np.abs(np.linalg.eigvals(op))))


def basin_fraction(z_fn, q_star, k, n, s2, s4, gamma, M=200, steps=1500):
    hits = 0
    for _ in range(M):
        q0 = np.exp(rng.uniform(-1.0, 1.0, size=n - 1))    # random positive prices
        out = tatonnement(z_fn, q0, k, n, steps=steps, s2=s2, s4=s4, gamma=gamma)
        if len(out["path"]) and np.max(np.abs(z_reduced(z_fn, out["path"][-1]))) < 1e-4:
            hits += 1
    return hits / M


# ── Experiment matrix ──────────────────────────────────────────────────────────────

GAMMA_SWEEP = [0.1, 0.2, 0.3, 0.5, 0.7, 0.9]


def best_s2_gamma(z_fn, q0, k, n, q_star):
    """S2 is model-free, so we cannot tune γ from the Jacobian — sweep and report the
    damping that best stabilises (lowest final distance). This IS the S2 calibration."""
    best = None
    for g in GAMMA_SWEEP:
        out = tatonnement(z_fn, q0, k, n, s2=True, gamma=g)
        q2 = q2_contraction(out["path"], q_star)
        if best is None or q2["d_final"] < best[1]["d_final"]:
            best = (g, q2, out)
    return best


def run():
    economies = {
        "scarf":            (scarf_excess_demand, 3, 0.10),
        "gross_substitute": (make_cobb_douglas(n=3, H=4), 3, 0.20),
    }
    results = {}
    for econ_name, (z_fn, n, k) in economies.items():
        q_star = find_equilibrium(z_fn, n)
        z_star = float(np.max(np.abs(z_reduced(z_fn, q_star))))
        q0 = np.array([2.0, 0.5])[:n - 1]
        cells = {}

        # S3 only
        out = tatonnement(z_fn, q0, k, n)
        q2 = q2_contraction(out["path"], q_star)
        cells["S3_only"] = {
            "converged": q2["d_final"] < 1e-3, "d_final": q2["d_final"],
            "Q2_lambda": q2["lambda"], "Q3_sigma_max": q3_sigma_max(z_fn, q_star, k, n),
            "basin_frac": basin_fraction(z_fn, q_star, k, n, False, False, 0.0),
        }
        # S3 + S2 (best γ)
        g, q2s2, _ = best_s2_gamma(z_fn, q0, k, n, q_star)
        cells["S3+S2"] = {
            "converged": q2s2["d_final"] < 1e-3, "d_final": q2s2["d_final"],
            "Q2_lambda": q2s2["lambda"], "gamma": g,
            "Q3_sigma_max": q3_sigma_max(z_fn, q_star, k, n, s2=True, gamma=g),
            "basin_frac": basin_fraction(z_fn, q_star, k, n, True, False, g),
        }
        # S3 + S4
        out = tatonnement(z_fn, q0, k, n, s4=True)
        q2s4 = q2_contraction(out["path"], q_star)
        cells["S3+S4"] = {
            "converged": q2s4["d_final"] < 1e-3, "d_final": q2s4["d_final"],
            "Q2_lambda": q2s4["lambda"],
            "Q3_sigma_max": q3_sigma_max(z_fn, q_star, k, n, s4=True),
            "basin_frac": basin_fraction(z_fn, q_star, k, n, False, True, 0.0),
        }
        results[econ_name] = {
            "p_star": to_p(q_star).tolist(), "z_at_p_star": z_star, "k": k, "cells": cells,
        }
    return results


def report(results):
    print("\n" + "═" * 80)
    print("EXP-LL-01 — Lange-Lerner tâtonnement under VSM structure — Fierro Q2/Q3")
    print("═" * 80)
    for econ, data in results.items():
        print(f"\n  ECONOMY: {econ}   p* = {[round(x,3) for x in data['p_star']]}   "
              f"k={data['k']}   (z@p* = {data['z_at_p_star']:.2e})")
        print(f"  {'config':<10}{'conv?':<7}{'d_final':<11}{'λ (Q2)':<11}"
              f"{'σmax (Q3)':<12}{'basin':<8}{'γ':<5}")
        print("  " + "-" * 70)
        for cfg, c in data["cells"].items():
            mark = "✓" if c["converged"] else "✗"
            lam = f"{c['Q2_lambda']:+.4f}" if np.isfinite(c["Q2_lambda"]) else "  n/a"
            g = f"{c.get('gamma',''):.1f}" if "gamma" in c else ""
            print(f"  {cfg:<10}{mark:<7}{c['d_final']:<11.2e}{lam:<11}"
                  f"{c['Q3_sigma_max']:<12.4f}{c['basin_frac']*100:>4.0f}%   {g}")
    print("\n  H_LL1 → [scarf, S3_only] should NOT converge; [scarf, S3+S2] and/or")
    print("          [scarf, S3+S4] SHOULD (basin↑, λ<0, σmax<1).")
    print("═" * 80)


if __name__ == "__main__":
    results = run()
    report(results)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ll01_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  results → {out_path}")
