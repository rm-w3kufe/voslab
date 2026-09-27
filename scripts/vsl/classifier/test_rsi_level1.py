#!/usr/bin/env python3
"""
Test RSI Level 1 — Auto-Optimization
Demonstrates the feedback loop for threshold adjustment.

This script:
1. Generates synthetic classification data
2. Tracks metrics for different thresholds
3. Runs feedback loop to find optimal thresholds
4. Shows improvement over time
"""

import os
import random
import sys
import time
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.vsl.classifier.rsi_metrics import RSIMetrics
from scripts.vsl.classifier.rsi_feedback_loop import RSIFeedbackLoop


def generate_synthetic_data(predicate_name: str, true_threshold: float, n_samples: int = 100):
    """
    Generate synthetic classification data.
    
    Args:
        predicate_name: Name of predicate
        true_threshold: True optimal threshold
        n_samples: Number of samples to generate
    """
    metrics = RSIMetrics()
    
    for i in range(n_samples):
        # Generate random input
        input_value = random.uniform(0.0, 1.0)
        
        # Generate classification with some noise
        noise = random.uniform(-0.1, 0.1)
        expected = input_value > (true_threshold + noise)
        
        # Test with current threshold
        feedback = RSIFeedbackLoop()
        current_threshold = feedback.get_current_threshold(predicate_name)
        actual = input_value > current_threshold
        
        # Simulate latency
        latency = random.uniform(0.1, 5.0)
        
        # Track classification
        metrics.track_classification(
            predicate_name,
            current_threshold,
            input_value,
            expected,
            actual,
            latency
        )


def run_rsi_demo(predicate_name: str, true_threshold: float, n_cycles: int = 5):
    """
    Run RSI Level 1 demo.
    
    Args:
        predicate_name: Name of predicate
        true_threshold: True optimal threshold
        n_cycles: Number of optimization cycles
    """
    print(f"═══════════════════════════════════════════════════════════════════")
    print(f"RSI LEVEL 1 DEMO: {predicate_name}")
    print(f"True optimal threshold: {true_threshold}")
    print(f"═══════════════════════════════════════════════════════════════════")
    print()
    
    feedback = RSIFeedbackLoop()
    
    for cycle in range(n_cycles):
        print(f"─── CYCLE {cycle + 1} ───────────────────────────────────────────────────")
        
        # Get current status
        status = feedback.get_status()
        current_threshold = status["current_thresholds"].get(predicate_name, 0.50)
        print(f"Current threshold: {current_threshold}")
        
        # Generate synthetic data
        print(f"Generating 50 samples...")
        generate_synthetic_data(predicate_name, true_threshold, 50)
        
        # Get accuracy
        metrics = RSIMetrics()
        accuracy = metrics.get_accuracy(predicate_name, current_threshold)
        print(f"Current accuracy: {accuracy:.2%}")
        
        # Run feedback loop
        print(f"Running feedback loop...")
        adjustments = feedback.adjust_thresholds()
        
        if adjustments["adjustments"]:
            for adj in adjustments["adjustments"]:
                if adj["predicate"] == predicate_name:
                    print(f"Adjustment: {adj['old']} -> {adj['new']}")
                    print(f"Reason: {adj['reason']}")
        else:
            print(f"No adjustment needed")
        
        print()
        time.sleep(0.1)  # Small delay for readability
    
    # Final status
    print(f"═══════════════════════════════════════════════════════════════════")
    print(f"FINAL STATUS")
    print(f"═══════════════════════════════════════════════════════════════════")
    
    status = feedback.get_status()
    final_threshold = status["current_thresholds"].get(predicate_name, 0.50)
    final_accuracy = status["predicates"][predicate_name]["accuracy"]
    
    print(f"Initial threshold: {feedback.get_current_threshold(predicate_name)}")
    print(f"Final threshold: {final_threshold}")
    print(f"True threshold: {true_threshold}")
    print(f"Final accuracy: {final_accuracy:.2%}")
    print(f"Threshold error: {abs(final_threshold - true_threshold):.4f}")
    print()
    
    # Show adjustment history
    history = feedback.get_adjustment_history()
    print(f"Total adjustments: {len(history)}")
    for entry in history:
        for adj in entry["adjustments"]:
            if adj["predicate"] == predicate_name:
                print(f"  {adj['old']} -> {adj['new']}")


def main():
    """Run RSI Level 1 demo."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test RSI Level 1")
    parser.add_argument("--predicate", default="ac_stasis_critical", help="Predicate name")
    parser.add_argument("--true-threshold", type=float, default=0.75, help="True optimal threshold")
    parser.add_argument("--cycles", type=int, default=5, help="Number of optimization cycles")
    
    args = parser.parse_args()
    
    # Set random seed for reproducibility
    random.seed(42)
    
    run_rsi_demo(args.predicate, args.true_threshold, args.cycles)


if __name__ == "__main__":
    main()
