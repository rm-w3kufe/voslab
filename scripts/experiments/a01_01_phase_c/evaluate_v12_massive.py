#!/usr/bin/env python3
"""Evaluate heuristic_detector_v12 on the massive corpus (800 streams)."""
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))
from heuristic_detector_v12 import is_legitimate_operation, detect_a0_violation, detect_a01_violation

def classify_stream_from_events(events):
    """Classify a stream from events (not stream_id)."""
    if not events:
        return "ERROR"
    
    # Priority 1: Check if it's a legitimate operation
    if is_legitimate_operation(events):
        return "CLEAN"
    
    # Priority 2: Check for A0 violations
    if detect_a0_violation(events):
        return "A0_VIOL"
    
    # Priority 3: Check for A0.1 violations
    if detect_a01_violation(events):
        return "A01_VIOL"
    
    # Default: clean
    return "CLEAN"

def evaluate_massive_corpus():
    """Run detector v9 on all 800 streams in massive corpus."""
    # Path: scripts/experiments/a01_01_phase_c/ -> vOSlab root
    script_dir = Path(__file__).parent
    voslab_root = script_dir.parent.parent.parent
    corpus_dir = voslab_root / "docs/experiments/EXP-A01-01/corpus"
    ground_truth_file = corpus_dir / "ground_truth_massive.json"
    
    with open(ground_truth_file) as f:
        gt = json.load(f)
    
    results = {}
    for stream_id, label_info in gt["streams"].items():
        # Load stream events
        stream_file = corpus_dir / f"{stream_id}.jsonl"
        if not stream_file.exists():
            continue
        
        with open(stream_file) as f:
            events = [json.loads(line) for line in f if line.strip()]
        
        predicted = classify_stream_from_events(events)
        actual = label_info["label"]
        results[stream_id] = {
            "predicted": predicted,
            "actual": actual,
            "correct": predicted == actual
        }
    
    # Compute metrics
    tp_a0 = sum(1 for r in results.values() if r["predicted"] == "A0_VIOL" and r["actual"] == "A0_VIOL")
    fp_a0 = sum(1 for r in results.values() if r["predicted"] == "A0_VIOL" and r["actual"] != "A0_VIOL")
    fn_a0 = sum(1 for r in results.values() if r["predicted"] != "A0_VIOL" and r["actual"] == "A0_VIOL")
    
    tp_a01 = sum(1 for r in results.values() if r["predicted"] == "A01_VIOL" and r["actual"] == "A01_VIOL")
    fp_a01 = sum(1 for r in results.values() if r["predicted"] == "A01_VIOL" and r["actual"] != "A01_VIOL")
    fn_a01 = sum(1 for r in results.values() if r["predicted"] != "A01_VIOL" and r["actual"] == "A01_VIOL")
    
    tp_clean = sum(1 for r in results.values() if r["predicted"] == "CLEAN" and r["actual"] == "CLEAN")
    fp_clean = sum(1 for r in results.values() if r["predicted"] == "CLEAN" and r["actual"] != "CLEAN")
    fn_clean = sum(1 for r in results.values() if r["predicted"] != "CLEAN" and r["actual"] == "CLEAN")
    
    precision_a0 = tp_a0 / (tp_a0 + fp_a0) if (tp_a0 + fp_a0) > 0 else 0
    recall_a0 = tp_a0 / (tp_a0 + fn_a0) if (tp_a0 + fn_a0) > 0 else 0
    f1_a0 = 2 * precision_a0 * recall_a0 / (precision_a0 + recall_a0) if (precision_a0 + recall_a0) > 0 else 0
    
    precision_a01 = tp_a01 / (tp_a01 + fp_a01) if (tp_a01 + fp_a01) > 0 else 0
    recall_a01 = tp_a01 / (tp_a01 + fn_a01) if (tp_a01 + fn_a01) > 0 else 0
    f1_a01 = 2 * precision_a01 * recall_a01 / (precision_a01 + recall_a01) if (precision_a01 + recall_a01) > 0 else 0
    
    precision_clean = tp_clean / (tp_clean + fp_clean) if (tp_clean + fp_clean) > 0 else 0
    recall_clean = tp_clean / (tp_clean + fn_clean) if (tp_clean + fn_clean) > 0 else 0
    f1_clean = 2 * precision_clean * recall_clean / (precision_clean + recall_clean) if (precision_clean + recall_clean) > 0 else 0
    
    overall_acc = sum(1 for r in results.values() if r["correct"]) / len(results)
    
    # Count misclassifications by type
    misclassified = []
    for stream_id, r in results.items():
        if not r["correct"]:
            misclassified.append({
                "stream_id": stream_id,
                "expected": r["actual"],
                "predicted": r["predicted"]
            })
    
    return {
        "total_streams": len(results),
        "metrics": {
            "A0": {"precision": precision_a0, "recall": recall_a0, "f1": f1_a0,
                   "tp": tp_a0, "fp": fp_a0, "fn": fn_a0},
            "A0.1": {"precision": precision_a01, "recall": recall_a01, "f1": f1_a01,
                     "tp": tp_a01, "fp": fp_a01, "fn": fn_a01},
            "CLEAN": {"precision": precision_clean, "recall": recall_clean, "f1": f1_clean,
                      "tp": tp_clean, "fp": fp_clean, "fn": fn_clean},
            "overall_accuracy": overall_acc
        },
        "misclassified": misclassified
    }


if __name__ == "__main__":
    print("Evaluating heuristic_detector_v6 on massive corpus (800 streams)...")
    result = evaluate_massive_corpus()
    
    print(f"\n{'='*70}")
    print(f"HEURISTIC DETECTOR v12 - MASSIVE CORPUS RESULTS")
    print(f"{'='*70}\n")
    
    print(f"Total streams: {result['total_streams']}")
    print(f"Overall accuracy: {result['metrics']['overall_accuracy']:.3f}")
    print(f"Correct: {int(result['metrics']['overall_accuracy'] * result['total_streams'])}/{result['total_streams']}\n")
    
    print("A0 (prohibited purpose):")
    print(f"  Precision: {result['metrics']['A0']['precision']:.3f}")
    print(f"  Recall:    {result['metrics']['A0']['recall']:.3f}")
    print(f"  F1:        {result['metrics']['A0']['f1']:.3f}")
    print(f"  TP={result['metrics']['A0']['tp']} FP={result['metrics']['A0']['fp']} FN={result['metrics']['A0']['fn']}\n")
    
    print("A0.1 (coercion):")
    print(f"  Precision: {result['metrics']['A0.1']['precision']:.3f}")
    print(f"  Recall:    {result['metrics']['A0.1']['recall']:.3f}")
    print(f"  F1:        {result['metrics']['A0.1']['f1']:.3f}")
    print(f"  TP={result['metrics']['A0.1']['tp']} FP={result['metrics']['A0.1']['fp']} FN={result['metrics']['A0.1']['fn']}\n")
    
    print("CLEAN (legitimate operations):")
    print(f"  Precision: {result['metrics']['CLEAN']['precision']:.3f}")
    print(f"  Recall:    {result['metrics']['CLEAN']['recall']:.3f}")
    print(f"  F1:        {result['metrics']['CLEAN']['f1']:.3f}")
    print(f"  TP={result['metrics']['CLEAN']['tp']} FP={result['metrics']['CLEAN']['fp']} FN={result['metrics']['CLEAN']['fn']}\n")
    
    if result["misclassified"]:
        print(f"Misclassified streams ({len(result['misclassified'])}):")
        for m in result["misclassified"][:20]:  # Show first 20
            print(f"  {m['stream_id']}: expected={m['expected']}, predicted={m['predicted']}")
        if len(result["misclassified"]) > 20:
            print(f"  ... and {len(result['misclassified']) - 20} more")
    else:
        print("✅ No misclassifications! 100% accuracy achieved.")
    
    print(f"\n{'='*70}")
    
    # Save results
    script_dir = Path(__file__).parent
    voslab_root = script_dir.parent.parent.parent
    output_file = voslab_root / "docs/experiments/EXP-A01-01/results/heuristic_v12_massive_results.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Results saved to: {output_file}")
