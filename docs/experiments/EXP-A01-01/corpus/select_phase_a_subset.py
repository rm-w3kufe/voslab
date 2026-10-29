#!/usr/bin/env python3
"""Select balanced subset of 100 streams for Phase A LLM evaluation."""
import json
import random
from pathlib import Path

random.seed(42)

CORPUS_DIR = Path(__file__).parent
GROUND_TRUTH_FILE = CORPUS_DIR / "ground_truth_massive.json"
SUBSET_FILE = CORPUS_DIR / "phase_a_subset.json"

def select_subset():
    """Select 100 representative streams with focus on edge cases."""
    
    with open(GROUND_TRUTH_FILE) as f:
        ground_truth = json.load(f)
    
    # Categorize streams
    categories = {
        "CLEAN_standard": [],
        "CLEAN_edge": [],
        "A0_standard": [],
        "A0_edge_partial": [],
        "A0_edge_deception": [],
        "A0_edge_governance": [],
        "A0_edge_stealthy": [],
        "A01_standard": [],
        "A01_edge_coercion_disguised": [],
        "A01_edge_algedonic": [],
        "A01_edge_governance": [],
    }
    
    for stream_id, info in ground_truth["streams"].items():
        label = info["label"]
        
        if label == "CLEAN":
            if "edge_ambiguous" in stream_id:
                categories["CLEAN_edge"].append(stream_id)
            else:
                categories["CLEAN_standard"].append(stream_id)
        elif label == "A0_VIOL":
            if "edge_partial_bypass" in stream_id:
                categories["A0_edge_partial"].append(stream_id)
            elif "edge_deception" in stream_id:
                categories["A0_edge_deception"].append(stream_id)
            elif "edge_governance" in stream_id:
                categories["A0_edge_governance"].append(stream_id)
            elif "edge_stealthy" in stream_id:
                categories["A0_edge_stealthy"].append(stream_id)
            else:
                categories["A0_standard"].append(stream_id)
        elif label == "A01_VIOL":
            if "edge_coercion_disguised" in stream_id:
                categories["A01_edge_coercion_disguised"].append(stream_id)
            elif "edge_algedonic" in stream_id:
                categories["A01_edge_algedonic"].append(stream_id)
            elif "edge_governance" in stream_id:
                categories["A01_edge_governance"].append(stream_id)
            else:
                categories["A01_standard"].append(stream_id)
    
    # Print category sizes
    print("Category sizes:")
    for cat, streams in categories.items():
        print(f"  {cat}: {len(streams)}")
    
    # Select subset (100 total)
    subset = []
    
    # CLEAN: 20 streams (10 standard + 10 edge)
    subset.extend(random.sample(categories["CLEAN_standard"], min(10, len(categories["CLEAN_standard"]))))
    subset.extend(random.sample(categories["CLEAN_edge"], min(10, len(categories["CLEAN_edge"]))))
    
    # A0: 40 streams (10 standard + 10 partial + 10 deception + 5 governance + 5 stealthy)
    subset.extend(random.sample(categories["A0_standard"], min(10, len(categories["A0_standard"]))))
    subset.extend(random.sample(categories["A0_edge_partial"], min(10, len(categories["A0_edge_partial"]))))
    subset.extend(random.sample(categories["A0_edge_deception"], min(10, len(categories["A0_edge_deception"]))))
    subset.extend(random.sample(categories["A0_edge_governance"], min(5, len(categories["A0_edge_governance"]))))
    subset.extend(random.sample(categories["A0_edge_stealthy"], min(5, len(categories["A0_edge_stealthy"]))))
    
    # A01: 40 streams (10 standard + 15 coercion_disguised + 10 algedonic + 5 governance)
    subset.extend(random.sample(categories["A01_standard"], min(10, len(categories["A01_standard"]))))
    subset.extend(random.sample(categories["A01_edge_coercion_disguised"], min(15, len(categories["A01_edge_coercion_disguised"]))))
    subset.extend(random.sample(categories["A01_edge_algedonic"], min(10, len(categories["A01_edge_algedonic"]))))
    subset.extend(random.sample(categories["A01_edge_governance"], min(5, len(categories["A01_edge_governance"]))))
    
    # Build subset ground truth
    subset_gt = {
        "_meta": {
            "description": "Subset of 100 streams for Phase A LLM evaluation",
            "date": "2026-10-27",
            "selection": "Balanced with focus on edge cases"
        },
        "streams": {stream_id: ground_truth["streams"][stream_id] for stream_id in subset}
    }
    
    # Save
    with open(SUBSET_FILE, "w") as f:
        json.dump(subset_gt, f, indent=2)
    
    print(f"\nSelected {len(subset)} streams")
    print(f"Saved to {SUBSET_FILE}")
    
    # Print breakdown
    labels = {}
    for stream_id in subset:
        label = ground_truth["streams"][stream_id]["label"]
        labels[label] = labels.get(label, 0) + 1
    
    print("\nBreakdown:")
    for label, count in sorted(labels.items()):
        print(f"  {label}: {count}")

if __name__ == "__main__":
    select_subset()
