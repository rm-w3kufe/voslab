#!/usr/bin/env python3
"""
Test RSI Level 3 — Auto-Generation
Demonstrates pattern detection and component generation.

This script:
1. Detects patterns in classification data
2. Generates new predicates based on patterns
3. Generates new trees based on patterns
4. Registers all components in system
5. Shows the auto-generation process
"""

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.vsl.classifier.rsi_metrics import RSIMetrics
from scripts.vsl.classifier.rsi_pattern_detector import RSIPatternDetector
from scripts.vsl.classifier.rsi_predicate_generator import RSIPredicateGenerator
from scripts.vsl.classifier.rsi_advanced_tree_generator import RSIAdvancedTreeGenerator
from scripts.vsl.classifier.rsi_component_registry import RSIComponentRegistry


def generate_diverse_data(predicate_name: str, n_samples: int = 100):
    """Generate diverse classification data to create patterns."""
    metrics = RSIMetrics()
    
    for i in range(n_samples):
        input_value = random.uniform(0.0, 1.0)
        
        # Create diverse patterns
        if random.random() < 0.2:  # 20% edge cases
            # Edge cases: very high or very low values
            expected = random.choice([True, False])
            actual = expected
            latency = random.uniform(0.1, 5.0)
        elif random.random() < 0.3:  # 30% fast execution
            # Fast execution cases
            expected = input_value > 0.7
            actual = expected
            latency = random.uniform(0.01, 0.1)
        else:  # 50% normal cases
            # Normal cases
            expected = input_value > 0.7
            actual = expected
            latency = random.uniform(0.1, 10.0)
        
        threshold = 0.7
        
        metrics.track_classification(
            predicate_name,
            threshold,
            input_value,
            expected,
            actual,
            latency
        )


def run_rsi_level3_demo(predicate_name: str, n_cycles: int = 3):
    """Run RSI Level 3 demo."""
    print(f"═══════════════════════════════════════════════════════════════════")
    print(f"RSI LEVEL 3 DEMO: {predicate_name}")
    print(f"═══════════════════════════════════════════════════════════════════")
    print()
    
    # Initialize components
    detector = RSIPatternDetector()
    predicate_gen = RSIPredicateGenerator()
    tree_gen = RSIAdvancedTreeGenerator()
    registry = RSIComponentRegistry()
    
    generated_predicates = []
    generated_trees = []
    
    for cycle in range(n_cycles):
        print(f"─── CYCLE {cycle + 1} ───────────────────────────────────────────────────")
        
        # Step 1: Generate diverse data
        print(f"Step 1: Generating diverse data...")
        generate_diverse_data(predicate_name, 50)
        
        # Step 2: Detect patterns
        print(f"Step 2: Detecting patterns...")
        patterns = detector.detect_patterns(predicate_name)
        print(f"  Found {len(patterns['patterns'])} patterns")
        
        for pattern in patterns["patterns"]:
            print(f"    {pattern['type']}: {pattern['severity']}")
        
        # Step 3: Generate components
        if patterns["patterns"]:
            for pattern in patterns["patterns"]:
                # Generate predicate
                print(f"Step 3a: Generating predicate for {pattern['type']}...")
                predicate_path = predicate_gen.generate_predicate({
                    "name": f"{predicate_name}_{pattern['type']}",
                    "purpose": pattern.get("suggestion", "Auto-generated predicate"),
                    "template": "edge_case_predicate" if pattern["type"] == "recurring_misclassification" else "generic_predicate"
                })
                print(f"  Generated predicate: {predicate_path}")
                generated_predicates.append(predicate_path)
                
                # Generate tree
                print(f"Step 3b: Generating tree for {pattern['type']}...")
                tree_path = tree_gen.generate_advanced_tree({
                    "name": f"{predicate_name}_{pattern['type']}",
                    "purpose": pattern.get("suggestion", "Auto-generated tree"),
                    "template": "threshold_optimized_tree" if pattern["type"] == "threshold_clustering" else "generic_tree",
                    "best_threshold": 0.7
                })
                print(f"  Generated tree: {tree_path}")
                generated_trees.append(tree_path)
                
                # Step 4: Register components
                print(f"Step 4: Registering components...")
                
                # Register predicate
                predicate_result = registry.register_component("predicate", predicate_path, f"{predicate_name}_{pattern['type']}")
                if predicate_result["success"]:
                    print(f"  Registered predicate: {predicate_path}")
                else:
                    print(f"  Predicate registration failed: {predicate_result['error']}")
                
                # Register tree
                tree_result = registry.register_component("tree", tree_path, f"{predicate_name}_{pattern['type']}")
                if tree_result["success"]:
                    print(f"  Registered tree: {tree_path}")
                else:
                    print(f"  Tree registration failed: {tree_result['error']}")
        else:
            print(f"Step 3: No patterns detected, skipping generation")
        
        print()
        time.sleep(0.1)
    
    # Final status
    print(f"═══════════════════════════════════════════════════════════════════")
    print(f"FINAL STATUS")
    print(f"═══════════════════════════════════════════════════════════════════")
    
    # Get registry stats
    stats = registry.get_registry_stats()
    print(f"Total components: {stats['total_components']}")
    print(f"Active components: {stats['active_components']}")
    print(f"Inactive components: {stats['inactive_components']}")
    print(f"By type: {stats['by_type']}")
    
    # Get patterns summary
    patterns_summary = detector.get_patterns_summary()
    print(f"Total patterns: {patterns_summary['total_patterns']}")
    print(f"By type: {patterns_summary['by_type']}")
    
    # List generated components
    print()
    print(f"Generated predicates: {len(generated_predicates)}")
    for predicate in generated_predicates:
        print(f"  {predicate}")
    
    print(f"Generated trees: {len(generated_trees)}")
    for tree in generated_trees:
        print(f"  {tree}")


def main():
    """Run RSI Level 3 demo."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test RSI Level 3")
    parser.add_argument("--predicate", default="ac_stasis_critical", help="Predicate name")
    parser.add_argument("--cycles", type=int, default=3, help="Number of cycles")
    
    args = parser.parse_args()
    
    # Set random seed for reproducibility
    random.seed(42)
    
    run_rsi_level3_demo(args.predicate, args.cycles)


if __name__ == "__main__":
    main()
