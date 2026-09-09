#!/usr/bin/env python3
"""
Test RSI Level 2 — Auto-Modification
Demonstrates gap detection and tree generation.

This script:
1. Detects gaps in classification
2. Generates new trees based on gaps
3. Registers trees in system
4. Shows the auto-modification process
"""

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.vsl.classifier.rsi_metrics import RSIMetrics
from scripts.vsl.classifier.rsi_gap_detector import RSIGapDetector
from scripts.vsl.classifier.rsi_tree_generator import RSITreeGenerator
from scripts.vsl.classifier.rsi_tree_registry import RSITreeRegistry


def generate_misclassifications(predicate_name: str, n_samples: int = 100):
    """Generate misclassifications to create gaps."""
    metrics = RSIMetrics()
    
    for i in range(n_samples):
        input_value = random.uniform(0.0, 1.0)
        
        # Create misclassifications
        if random.random() < 0.3:  # 30% misclassification rate
            expected = random.choice([True, False])
            actual = not expected  # Wrong classification
        else:
            expected = input_value > 0.7
            actual = expected
        
        threshold = 0.7
        latency = random.uniform(0.1, 15.0)  # Some high latency
        
        metrics.track_classification(
            predicate_name,
            threshold,
            input_value,
            expected,
            actual,
            latency
        )


def run_rsi_level2_demo(predicate_name: str, n_cycles: int = 3):
    """Run RSI Level 2 demo."""
    print(f"═══════════════════════════════════════════════════════════════════")
    print(f"RSI LEVEL 2 DEMO: {predicate_name}")
    print(f"═══════════════════════════════════════════════════════════════════")
    print()
    
    # Initialize components
    detector = RSIGapDetector()
    generator = RSITreeGenerator()
    registry = RSITreeRegistry()
    
    for cycle in range(n_cycles):
        print(f"─── CYCLE {cycle + 1} ───────────────────────────────────────────────────")
        
        # Step 1: Generate misclassifications
        print(f"Step 1: Generating misclassifications...")
        generate_misclassifications(predicate_name, 50)
        
        # Step 2: Detect gaps
        print(f"Step 2: Detecting gaps...")
        gaps = detector.detect_gaps(predicate_name)
        print(f"  Found {len(gaps['gaps'])} gaps")
        
        for gap in gaps["gaps"]:
            print(f"    {gap['type']}: {gap['severity']}")
        
        # Step 3: Generate tree
        if gaps["gaps"]:
            print(f"Step 3: Generating new tree...")
            tree_path = generator.generate_tree(predicate_name, gaps)
            print(f"  Generated: {tree_path}")
            
            # Step 4: Register tree
            print(f"Step 4: Registering tree...")
            result = registry.register_tree(tree_path, predicate_name, {
                "generated_cycle": cycle + 1,
                "gaps_count": len(gaps["gaps"])
            })
            
            if result["success"]:
                print(f"  Registered successfully")
            else:
                print(f"  Registration failed: {result['error']}")
        else:
            print(f"Step 3: No gaps detected, skipping tree generation")
        
        print()
        time.sleep(0.1)
    
    # Final status
    print(f"═══════════════════════════════════════════════════════════════════")
    print(f"FINAL STATUS")
    print(f"═══════════════════════════════════════════════════════════════════")
    
    # Get registry stats
    stats = registry.get_registry_stats()
    print(f"Total trees: {stats['total_trees']}")
    print(f"Active trees: {stats['active_trees']}")
    print(f"Inactive trees: {stats['inactive_trees']}")
    
    # Get gaps summary
    gaps_summary = detector.get_gaps_summary()
    print(f"Total gaps: {gaps_summary['total_gaps']}")
    print(f"High severity: {gaps_summary['high_severity']}")
    print(f"Medium severity: {gaps_summary['medium_severity']}")
    
    # List generated trees
    print()
    print(f"Generated trees:")
    generated_trees = generator.get_generated_trees()
    for tree in generated_trees:
        print(f"  {tree['predicate']}: {tree['path']}")


def main():
    """Run RSI Level 2 demo."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test RSI Level 2")
    parser.add_argument("--predicate", default="ac_stasis_critical", help="Predicate name")
    parser.add_argument("--cycles", type=int, default=3, help="Number of cycles")
    
    args = parser.parse_args()
    
    # Set random seed for reproducibility
    random.seed(42)
    
    run_rsi_level2_demo(args.predicate, args.cycles)


if __name__ == "__main__":
    main()
