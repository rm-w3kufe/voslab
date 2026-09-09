#!/usr/bin/env python3
"""
Demo: Evaluate system/boot files using Socratic Engine
Shows how the socratic engine can classify and evaluate core system documents.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone

# ── Configuration ────────────────────────────────────────────────────
BOOT_DIR = Path(__file__).parent.parent.parent.parent / "docs" / "spec_revision" / "system" / "boot"
TREES_DIR = Path(__file__).parent.parent.parent.parent / ".opencode" / "plugins" / "support" / "trees"


def print_header(title: str):
    """Print formatted header."""
    print()
    print("═" * 70)
    print(f"  {title}")
    print("═" * 70)
    print()


def print_section(title: str):
    """Print formatted section."""
    print()
    print(f"┌─ {title}")
    print("│")


def print_result(label: str, value):
    """Print formatted result."""
    print(f"│  {label}: {value}")


def print_footer():
    """Print formatted footer."""
    print("│")
    print("└" + "─" * 69)


def load_boot_files():
    """Load all boot files."""
    boot_files = {}
    
    for file_path in BOOT_DIR.glob("*.vsm"):
        with open(file_path, 'r') as f:
            content = f.read()
            boot_files[file_path.name] = {
                "path": str(file_path),
                "content": content,
                "size": len(content),
                "lines": content.count('\n') + 1
            }
    
    return boot_files


def analyze_vsm_structure(content: str) -> dict:
    """Analyze VSM structure of a file."""
    analysis = {
        "has_header": "⟦" in content and "⟧" in content,
        "has_vsm_version": "@vsm 1.2" in content,
        "has_status": "@status" in content,
        "has_footer": "⟦ /" in content,
        "has_decision": "decision(" in content,
        "has_context": "$ctx" in content,
        "has_operators": any(op in content for op in ["AND(", "OR(", "NOT(", "TRUE"]),
        "has_predicates": any(pred in content for pred in ["ctx_equals", "ctx_has", "ctx_has_value"]),
        "block_count": content.count("⟦"),
        "line_count": content.count('\n') + 1,
        "char_count": len(content)
    }
    
    return analysis


def classify_boot_file(filename: str, analysis: dict) -> dict:
    """Classify boot file based on analysis."""
    classification = {
        "filename": filename,
        "type": "unknown",
        "complexity": "unknown",
        "purpose": "unknown"
    }
    
    # Classify by type
    if "covenant" in filename.lower():
        classification["type"] = "governance"
        classification["purpose"] = "Defines governance rules and constraints"
    elif "hard_rules" in filename.lower():
        classification["type"] = "rules"
        classification["purpose"] = "Hard rules that cannot be violated"
    elif "boot" in filename.lower() and "manifest" in filename.lower():
        classification["type"] = "manifest"
        classification["purpose"] = "System manifest and configuration"
    elif "primer" in filename.lower():
        classification["type"] = "reference"
        classification["purpose"] = "Reference documentation"
    elif "protocol" in filename.lower():
        classification["type"] = "protocol"
        classification["purpose"] = "Communication protocols"
    elif "regulation" in filename.lower():
        classification["type"] = "regulation"
        classification["purpose"] = "Regulatory framework"
    elif "classification" in filename.lower():
        classification["type"] = "classification"
        classification["purpose"] = "Classification system"
    else:
        classification["type"] = "document"
        classification["purpose"] = "General document"
    
    # Classify by complexity
    if analysis["line_count"] > 500:
        classification["complexity"] = "high"
    elif analysis["line_count"] > 200:
        classification["complexity"] = "medium"
    else:
        classification["complexity"] = "low"
    
    return classification


def evaluate_with_socratic(filename: str, content: str) -> dict:
    """Evaluate file using socratic engine concepts."""
    evaluation = {
        "filename": filename,
        "vsm_compliance": 0,
        "structure_score": 0,
        "completeness": 0,
        "recommendations": []
    }
    
    # Check VSM compliance
    if "⟦" in content and "⟧" in content:
        evaluation["vsm_compliance"] += 25
    if "@vsm 1.2" in content:
        evaluation["vsm_compliance"] += 25
    if "@status" in content:
        evaluation["vsm_compliance"] += 25
    if "⟦ /" in content:
        evaluation["vsm_compliance"] += 25
    
    # Check structure
    if "decision(" in content:
        evaluation["structure_score"] += 30
    if "$ctx" in content:
        evaluation["structure_score"] += 30
    if any(op in content for op in ["AND(", "OR(", "NOT("]):
        evaluation["structure_score"] += 20
    if any(pred in content for pred in ["ctx_equals", "ctx_has"]):
        evaluation["structure_score"] += 20
    
    # Check completeness
    if len(content) > 1000:
        evaluation["completeness"] += 30
    if content.count('\n') > 50:
        evaluation["completeness"] += 30
    if "TODO" not in content and "FIXME" not in content:
        evaluation["completeness"] += 40
    
    # Generate recommendations
    if evaluation["vsm_compliance"] < 100:
        evaluation["recommendations"].append("Improve VSM compliance")
    if evaluation["structure_score"] < 100:
        evaluation["recommendations"].append("Add more structure (decision trees, context)")
    if evaluation["completeness"] < 100:
        evaluation["recommendations"].append("Improve completeness")
    
    return evaluation


def run_demo():
    """Run the demo."""
    print_header("DEMO: EVALUATION OF system/boot FILES")
    print(f"  Using Socratic Engine Concepts")
    print(f"  Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # Step 1: Load boot files
    print_section("Step 1: Load boot files")
    boot_files = load_boot_files()
    print_result("Files found", len(boot_files))
    for filename in boot_files:
        print_result(f"  {filename}", f"{boot_files[filename]['lines']} lines")
    print_footer()
    
    # Step 2: Analyze VSM structure
    print_section("Step 2: Analyze VSM structure")
    analyses = {}
    for filename, file_data in boot_files.items():
        analysis = analyze_vsm_structure(file_data["content"])
        analyses[filename] = analysis
        
        print_result(f"\n  {filename}", "")
        print_result("    Has header (⟦⟧)", "✓" if analysis["has_header"] else "✗")
        print_result("    Has @vsm 1.2", "✓" if analysis["has_vsm_version"] else "✗")
        print_result("    Has @status", "✓" if analysis["has_status"] else "✗")
        print_result("    Has footer", "✓" if analysis["has_footer"] else "✗")
        print_result("    Has decision()", "✓" if analysis["has_decision"] else "✗")
        print_result("    Has $ctx", "✓" if analysis["has_context"] else "✗")
    print_footer()
    
    # Step 3: Classify files
    print_section("Step 3: Classify boot files")
    classifications = {}
    for filename, analysis in analyses.items():
        classification = classify_boot_file(filename, analysis)
        classifications[filename] = classification
        
        print_result(f"\n  {filename}", "")
        print_result("    Type", classification["type"])
        print_result("    Complexity", classification["complexity"])
        print_result("    Purpose", classification["purpose"])
    print_footer()
    
    # Step 4: Evaluate with socratic engine
    print_section("Step 4: Evaluate with socratic engine")
    evaluations = {}
    for filename, file_data in boot_files.items():
        evaluation = evaluate_with_socratic(filename, file_data["content"])
        evaluations[filename] = evaluation
        
        print_result(f"\n  {filename}", "")
        print_result("    VSM compliance", f"{evaluation['vsm_compliance']}%")
        print_result("    Structure score", f"{evaluation['structure_score']}%")
        print_result("    Completeness", f"{evaluation['completeness']}%")
        
        if evaluation["recommendations"]:
            print_result("    Recommendations", ", ".join(evaluation["recommendations"]))
    print_footer()
    
    # Step 5: Summary
    print_section("Step 5: Summary")
    
    # Calculate overall scores
    total_vsm = sum(e["vsm_compliance"] for e in evaluations.values()) / len(evaluations)
    total_structure = sum(e["structure_score"] for e in evaluations.values()) / len(evaluations)
    total_completeness = sum(e["completeness"] for e in evaluations.values()) / len(evaluations)
    
    print_result("Overall VSM compliance", f"{total_vsm:.1f}%")
    print_result("Overall structure score", f"{total_structure:.1f}%")
    print_result("Overall completeness", f"{total_completeness:.1f}%")
    print_result("Total files evaluated", len(evaluations))
    
    # Count by type
    type_counts = {}
    for classification in classifications.values():
        file_type = classification["type"]
        type_counts[file_type] = type_counts.get(file_type, 0) + 1
    
    print_result("\nFiles by type", "")
    for file_type, count in type_counts.items():
        print_result(f"  {file_type}", count)
    
    print_footer()
    
    print_header("DEMO COMPLETE")
    print("  The socratic engine successfully evaluated the boot files.")
    print("  This demonstrates how the system can analyze and classify")
    print("  core documents using structured evaluation.")
    print()


def main():
    """Run demo."""
    run_demo()


if __name__ == "__main__":
    main()
