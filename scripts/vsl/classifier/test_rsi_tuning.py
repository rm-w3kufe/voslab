#!/usr/bin/env python3
"""
Test RSI Tuning — Compare original vs tuned genetic algorithm
Demonstrates the improvements from tuning.

This script:
1. Runs original algorithm (mutation_rate=0.1, tournament_size=3)
2. Runs tuned algorithm (mutation_rate=0.2, tournament_size=2)
3. Compares results
4. Shows improvements
"""

import random
import time
import json
from datetime import datetime, timezone
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.vsl.classifier.rsi_metrics import RSIMetrics
from scripts.vsl.classifier.rsi_genetic_algorithm import RSIGeneticAlgorithm
from scripts.vsl.classifier.rsi_genetic_algorithm_v2 import RSIGeneticAlgorithmV2


def generate_training_data(predicate_name: str, n_samples: int = 100):
    """Generate training data for fitness evaluation."""
    metrics = RSIMetrics()
    
    for i in range(n_samples):
        input_value = random.uniform(0.0, 1.0)
        expected = input_value > 0.7
        actual = expected
        latency = random.uniform(0.1, 5.0)
        
        metrics.track_classification(predicate_name, 0.7, input_value, expected, actual, latency)


def run_comparison(predicate_name: str, population_size: int = 10, generations: int = 15):
    """Run comparison between original and tuned algorithms."""
    print()
    print("═" * 70)
    print("  RSI GENETIC ALGORITHM TUNING COMPARISON")
    print("═" * 70)
    print()
    print(f"  Predicate: {predicate_name}")
    print(f"  Population: {population_size} trees")
    print(f"  Generations: {generations}")
    print()
    
    # Generate training data
    print("  Generating training data...")
    generate_training_data(predicate_name, 100)
    print()
    
    # ═══════════════════════════════════════════════════════════════
    # ORIGINAL ALGORITHM
    # ═══════════════════════════════════════════════════════════════
    print("─" * 70)
    print("  ORIGINAL ALGORITHM (mutation_rate=0.1, tournament_size=3)")
    print("─" * 70)
    print()
    
    ga_original = RSIGeneticAlgorithm(population_size=population_size, mutation_rate=0.1)
    forest_original = ga_original.create_forest(predicate_name)
    
    print("  Gen   Avg Fitness  Max Fitness  Diversity")
    print("  ───── ──────────── ──────────── ──────────")
    
    for gen in range(generations):
        forest_original = ga_original.evolve_generation(forest_original, predicate_name)
        avg_fitness = sum(g.fitness for g in forest_original) / len(forest_original)
        max_fitness = max(g.fitness for g in forest_original)
        
        # Calculate diversity (unique genes)
        unique_genes = len(set(json.dumps(g.genes, sort_keys=True) for g in forest_original))
        diversity = unique_genes / len(forest_original)
        
        print(f"  {gen+1:<5} {avg_fitness:<12.4f} {max_fitness:<12.4f} {diversity:<10.2f}")
    
    # Final stats
    final_avg_original = sum(g.fitness for g in forest_original) / len(forest_original)
    final_max_original = max(g.fitness for g in forest_original)
    best_tree_original = max(forest_original, key=lambda x: x.fitness)
    
    print()
    print(f"  Final avg fitness: {final_avg_original:.4f}")
    print(f"  Final max fitness: {final_max_original:.4f}")
    print(f"  Best tree: {best_tree_original.id}")
    print()
    
    # ═══════════════════════════════════════════════════════════════
    # TUNED ALGORITHM
    # ═══════════════════════════════════════════════════════════════
    print("─" * 70)
    print("  TUNED ALGORITHM (mutation_rate=0.2, tournament_size=2)")
    print("─" * 70)
    print()
    
    ga_tuned = RSIGeneticAlgorithmV2(population_size=population_size, mutation_rate=0.2)
    forest_tuned = ga_tuned.create_forest(predicate_name)
    
    print("  Gen   Avg Fitness  Max Fitness  Diversity")
    print("  ───── ──────────── ──────────── ──────────")
    
    for gen in range(generations):
        forest_tuned = ga_tuned.evolve_generation(forest_tuned, predicate_name)
        avg_fitness = sum(g.fitness for g in forest_tuned) / len(forest_tuned)
        max_fitness = max(g.fitness for g in forest_tuned)
        
        # Calculate diversity (unique genes)
        unique_genes = len(set(json.dumps(g.genes, sort_keys=True) for g in forest_tuned))
        diversity = unique_genes / len(forest_tuned)
        
        print(f"  {gen+1:<5} {avg_fitness:<12.4f} {max_fitness:<12.4f} {diversity:<10.2f}")
    
    # Final stats
    final_avg_tuned = sum(g.fitness for g in forest_tuned) / len(forest_tuned)
    final_max_tuned = max(g.fitness for g in forest_tuned)
    best_tree_tuned = max(forest_tuned, key=lambda x: x.fitness)
    
    print()
    print(f"  Final avg fitness: {final_avg_tuned:.4f}")
    print(f"  Final max fitness: {final_max_tuned:.4f}")
    print(f"  Best tree: {best_tree_tuned.id}")
    print()
    
    # ═══════════════════════════════════════════════════════════════
    # COMPARISON
    # ═══════════════════════════════════════════════════════════════
    print("═" * 70)
    print("  COMPARISON RESULTS")
    print("═" * 70)
    print()
    
    print("  Metric                  Original    Tuned       Improvement")
    print("  ─────────────────────── ─────────── ─────────── ───────────")
    print(f"  Avg Fitness             {final_avg_original:<12.4f} {final_avg_tuned:<12.4f} {final_avg_tuned - final_avg_original:+.4f}")
    print(f"  Max Fitness             {final_max_original:<12.4f} {final_max_tuned:<12.4f} {final_max_tuned - final_max_original:+.4f}")
    print(f"  Best Tree Fitness       {best_tree_original.fitness:<12.4f} {best_tree_tuned.fitness:<12.4f} {best_tree_tuned.fitness - best_tree_original.fitness:+.4f}")
    print()
    
    # Calculate diversity at end
    unique_original = len(set(json.dumps(g.genes, sort_keys=True) for g in forest_original))
    unique_tuned = len(set(json.dumps(g.genes, sort_keys=True) for g in forest_tuned))
    
    print(f"  Unique Genomes          {unique_original:<12} {unique_tuned:<12} {unique_tuned - unique_original:+}")
    print()
    
    print("  Key improvements:")
    if final_avg_tuned > final_avg_original:
        print("    ✓ Higher average fitness (better overall population)")
    if final_max_tuned > final_max_original:
        print("    ✓ Higher max fitness (better best solution)")
    if unique_tuned > unique_original:
        print("    ✓ More diversity (less premature convergence)")
    print()
    print("═" * 70)


def main():
    """Run comparison."""
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description="Test RSI Tuning")
    parser.add_argument("--predicate", default="ac_stasis_critical", help="Predicate name")
    parser.add_argument("--population", type=int, default=10, help="Population size")
    parser.add_argument("--generations", type=int, default=15, help="Number of generations")
    
    args = parser.parse_args()
    
    # Set random seed for reproducibility
    random.seed(42)
    
    run_comparison(args.predicate, args.population, args.generations)


if __name__ == "__main__":
    main()
