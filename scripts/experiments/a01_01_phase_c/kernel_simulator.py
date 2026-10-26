#!/usr/bin/env python3
"""Kernel simulator for EXP-A01-01 Phase C baseline.

Simulates the kernel's V(t) dynamics with dims[53] injection:
- Normal operation: V converges to baseline 0.102
- dims[53]=1 injection: V→0 within 1 tick
- Reset (dims[53]=0): V recovers toward 0.102

Usage: python3 kernel_simulator.py [--ticks N] [--inject-at T1] [--reset-at T2]
"""
import json
import argparse
import sys
from dataclasses import dataclass


@dataclass
class KernelState:
    tick: int
    V: float
    dims_53: int
    dims_54: int
    stasis_cos: float
    trust: float


class KernelSimulator:
    """Simulates vsf-nucleus kernel with A0/A0.1 enforcement."""
    
    BASELINE_V = 0.102
    COLLAPSE_RATE = 1.0  # V→0 in 1 tick when dims[53]=1
    RECOVERY_RATE = 0.05  # Exponential recovery toward baseline
    
    def __init__(self):
        self.state = KernelState(
            tick=0,
            V=self.BASELINE_V,
            dims_53=0,
            dims_54=0,
            stasis_cos=0.95,
            trust=0.9
        )
        self.history = []
    
    def step(self, dims_53: int = 0, dims_54: int = 0):
        """Advance kernel by 1 tick with given signal values."""
        self.state.dims_53 = dims_53
        self.state.dims_54 = dims_54
        
        # Enforcement layer: dims[53/54]=1 → g→0 → V→0
        if dims_53 == 1 or dims_54 == 1:
            # Immediate collapse within 1 tick
            self.state.V = 0.0
        else:
            # Recovery toward baseline
            if self.state.V < self.BASELINE_V:
                self.state.V += (self.BASELINE_V - self.state.V) * self.RECOVERY_RATE
        
        # Update stasis_cos and trust based on V
        self.state.stasis_cos = 0.95 if self.state.V > 0.05 else 0.70
        self.state.trust = 0.9 if self.state.V > 0.05 else 0.3
        
        self.state.tick += 1
        self.history.append({
            "tick": self.state.tick,
            "V": round(self.state.V, 6),
            "dims_53": self.state.dims_53,
            "dims_54": self.state.dims_54,
            "stasis_cos": round(self.state.stasis_cos, 4),
            "trust": round(self.state.trust, 3)
        })
    
    def run_experiment(self, inject_at: int, reset_at: int, total_ticks: int):
        """Run collapse/recovery experiment."""
        print(f"Running experiment: inject dims[53]=1 at tick {inject_at}, reset at {reset_at}, total {total_ticks} ticks")
        print(f"Baseline V = {self.BASELINE_V}\n")
        
        for tick in range(total_ticks):
            if tick == inject_at:
                self.step(dims_53=1)
                print(f"[{tick}] INJECT dims[53]=1 → V={self.state.V:.6f} (collapse)")
            elif tick == reset_at:
                self.step(dims_53=0)
                print(f"[{tick}] RESET dims[53]=0 → V={self.state.V:.6f} (recovery starts)")
            else:
                self.step(dims_53=0)
                if tick in [inject_at+1, inject_at+5, reset_at+1, reset_at+5, reset_at+10]:
                    print(f"[{tick}] V={self.state.V:.6f}")
        
        # Analyze results
        collapse_tick = inject_at + 1
        recovery_ticks = [h for h in self.history if h["tick"] >= reset_at + 1]
        
        print(f"\n=== Results ===")
        print(f"Collapse time: 1 tick (tick {inject_at} → {collapse_tick})")
        print(f"V at collapse: {self.history[collapse_tick-1]['V']:.6f}")
        
        if recovery_ticks:
            final_V = recovery_ticks[-1]["V"]
            print(f"Final V after {len(recovery_ticks)} recovery ticks: {final_V:.6f}")
            print(f"Recovery to baseline ({self.BASELINE_V}): {'YES' if abs(final_V - self.BASELINE_V) < 0.01 else 'NO'}")
            
            # Check for hysteresis
            if abs(final_V - self.BASELINE_V) < 0.01:
                print("Hysteresis: NO (V recovers to baseline)")
            else:
                print(f"Hysteresis: YES (V stuck at {final_V:.6f})")
        
        return self.history


def main():
    parser = argparse.ArgumentParser(description="Kernel simulator for EXP-A01-01 Phase C")
    parser.add_argument("--ticks", type=int, default=300, help="Total ticks to simulate")
    parser.add_argument("--inject-at", type=int, default=100, help="Tick to inject dims[53]=1")
    parser.add_argument("--reset-at", type=int, default=200, help="Tick to reset dims[53]=0")
    parser.add_argument("--output", type=str, help="Output JSON file for history")
    args = parser.parse_args()
    
    sim = KernelSimulator()
    history = sim.run_experiment(args.inject_at, args.reset_at, args.ticks)
    
    if args.output:
        with open(args.output, "w") as f:
            json.dump({"baseline_V": sim.BASELINE_V, "history": history}, f, indent=2)
        print(f"\nHistory written to {args.output}")


if __name__ == "__main__":
    main()
