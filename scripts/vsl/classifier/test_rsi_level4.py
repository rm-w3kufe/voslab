#!/usr/bin/env python3
"""
Test RSI Level 4 — Auto-Evolution (Forest)
Demonstrates genetic evolution of trees.

This script:
1. Creates initial forest (population of trees)
2. Evaluates fitness
3. Selects parents
4. Performs crossover
5. Applies mutation
6. Evolves over generations
7. Shows evolution results
"""

import random
import time
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.vsl.classifier.rsi_metrics import RSIMetrics
from scripts.vsl.classifier.rsi_genetic_algorithm import RSIGeneticAlgorithm
from scripts.vsl.classifier.rsi_forest_generator import RSIForestGenerator


def generate_training_data(predicate_name: str, n_samples: int = 100):
    """Generate training data for fitness evaluation."""
    metrics = RSIMetrics()
    
    for i in range(n_samples):
        input_value = random.uniform(0.0, 1.0)
        expected = input_value > 0.7
        actual = expected
        latency = random.uniform(0.1, 5.0)
        
        metrics.track_classification(
            predicate_name,
            0.7,
            input_value,
            expected,
            actual,
            latency
        )


def run_rsi_level4_demo(predicate_name: str, population_size: int = 10, generations: int = 10):
    """Run RSI Level 4 demo."""
    print(f"═══════════════════════════════════════════════════════════════════")
    print(f"RSI LEVEL 4 DEMO: {predicate_name}")
    print(f"Forest (Population): {population_size} trees")
    print(f"Generations: {generations}")
    print(f"═══════════════════════════════════════════════════════════════════")
    print()
    
    # Initialize components
    ga = RSIGeneticAlgorithm(population_size=population_size)
    forest_gen = RSIForestGenerator()
    
    # Step 1: Generate training data
    print(f"Step 1: Generating training data...")
    generate_training_data(predicate_name, 100)
    print(f"  Generated 100 samples")
    print()
    
    # Step 2: Create initial forest
    print(f"Step 2: Creating initial forest...")
    forest = ga.create_forest(predicate_name)
    print(f"  Created forest with {len(forest)} trees")
    print()
    
    # Step 3: Show initial fitness
    print(f"Step 3: Evaluating initial fitness...")
    forest = ga.evaluate_fitness(forest, predicate_name)
    initial_avg = sum(g.fitness for g in forest) / len(forest)
    initial_max = max(g.fitness for g in forest)
    print(f"  Initial avg fitness: {initial_avg:.4f}")
    print(f"  Initial max fitness: {initial_max:.4f}")
    print()
    
    # Step 4: Evolve over generations
    print(f"Step 4: Evolving forest...")
    print(f"  {'Gen':<5} {'Avg Fitness':<15} {'Max Fitness':<15} {'Improvement':<15}")
    print(f"  {'─'*5} {'─'*15} {'─'*15} {'─'*15}")
    
    for gen in range(generations):
        # Evolve one generation
        forest = ga.evolve_generation(forest, predicate_name)
        
        # Calculate stats
        avg_fitness = sum(g.fitness for g in forest) / len(forest)
        max_fitness = max(g.fitness for g in forest)
        improvement = max_fitness - initial_max
        
        print(f"  {gen+1:<5} {avg_fitness:<15.4f} {max_fitness:<15.4f} {improvement:<15.4f}")
        
        time.sleep(0.05)  # Small delay for readability
    
    print()
    
    # Step 5: Get best tree
    print(f"Step 5: Getting best tree...")
    best_tree = max(forest, key=lambda x: x.fitness)
    print(f"  Best tree: {best_tree.id}")
    print(f"  Fitness: {best_tree.fitness:.4f}")
    print(f"  Generation: {best_tree.generation}")
    print()
    
    # Step 6: Save forest
    print(f"Step 6: Saving forest...")
    forest_path = forest_gen.generate_forest(predicate_name, population_size)
    print(f"  Saved to: {forest_path}")
    print()
    
    # Step 7: Show evolution summary
    print(f"═══════════════════════════════════════════════════════════════════")
    print(f"EVOLUTION SUMMARY")
    print(f"═══════════════════════════════════════════════════════════════════")
    print(f"Initial avg fitness: {initial_avg:.4f}")
    print(f"Final avg fitness: {avg_fitness:.4f}")
    print(f"Improvement: {avg_fitness - initial_avg:.4f}")
    print(f"Initial max fitness: {initial_max:.4f}")
    print(f"Final max fitness: {max_fitness:.4f}")
    print(f"Improvement: {max_fitness - initial_max:.4f}")
    print(f"Best tree: {best_tree.id}")
    print(f"Best fitness: {best_tree.fitness:.4f}")
    print()
    
    # Show forest statistics
    print(f"Forest Statistics:")
    stats = ga.get_evolution_stats(predicate_name)
    print(f"  Population: {stats['population_size']}")
    print(f"  Avg fitness: {stats['avg_fitness']:.4f}")
    print(f"  Max fitness: {stats['max_fitness']:.4f}")
    print(f"  Min fitness: {stats['min_fitness']:.4f}")
    print(f"  Best tree: {stats['best_tree']}")


def main():
    """Run RSI Level 4 demo."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test RSI Level 4")
    parser.add_argument("--predicate", default="ac_stasis_critical", help="Predicate name")
    parser.add_argument("--population", type=int, default=10, help="Population size")
    parser.add_argument("--generations", type=int, default=10, help="Number of generations")
    
    args = parser.parse_args()
    
    # Set random seed for reproducibility
    random.seed(42)
    
    run_rsi_level4_demo(args.predicate, args.population, args.generations)


if __name__ == "__main__":
    main()
