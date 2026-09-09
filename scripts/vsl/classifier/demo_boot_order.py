#!/usr/bin/env python3
"""
Demo: Analyze logical dependencies in boot files to determine ideal load order
Uses socratic engine concepts to evaluate consistency and dependencies.
"""

import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Set, Tuple
from collections import defaultdict

# ── Configuration ────────────────────────────────────────────────────
BOOT_DIR = Path(__file__).parent.parent.parent.parent / "docs" / "spec_revision" / "system" / "boot"


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


def load_boot_files() -> Dict[str, str]:
    """Load all boot files."""
    boot_files = {}
    
    for file_path in BOOT_DIR.glob("*.vsm"):
        with open(file_path, 'r') as f:
            boot_files[file_path.name] = f.read()
    
    return boot_files


def extract_references(content: str) -> Set[str]:
    """Extract references to other boot files."""
    references = set()
    
    # Common reference patterns
    patterns = [
        r'(?:see|ref|reference|cf\.|compare)\s+(\w+\.vsm)',
        r'(?:defined in|from|in)\s+(\w+\.vsm)',
        r'R\d+(?:\.\d+)?\s*\(([^)]+)\)',
        r'@see\s+(\w+\.vsm)',
        r'\[\[([^\]]+)\]\]',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            # Clean up the reference
            ref = match.strip()
            if ref.endswith('.vsm'):
                references.add(ref)
            elif ref in ['covenant', 'hard_rules', 'core_boot_primer', 'vsl_language_primer',
                        'boot_manifest', 'classification.local', 'communication_protocol',
                        'regulation_layer']:
                references.add(f"{ref}.vsm")
    
    return references


def extract_rules(content: str) -> List[str]:
    """Extract rules from content."""
    rules = []
    
    # Pattern for rules (R1, R2, etc.)
    rule_pattern = r'(R\d+(?:\.\d+)?)\s*[:\-=]\s*([^\n]+)'
    matches = re.findall(rule_pattern, content)
    
    for rule_id, rule_desc in matches:
        rules.append(f"{rule_id}: {rule_desc.strip()}")
    
    return rules


def extract_concepts(content: str) -> Set[str]:
    """Extract key concepts from content."""
    concepts = set()
    
    # Common VSM concepts
    concept_patterns = [
        r'(?:S\d+|organ|recursion|level|hierarchy)',
        r'(?:φ|algedonic|signal|channel)',
        r'(?:VSM|viable|system|model)',
        r'(?:decision|tree|predicate|operator)',
        r'(?:context|metadata|state)',
    ]
    
    for pattern in concept_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        concepts.update(matches)
    
    return concepts


def analyze_dependencies(boot_files: Dict[str, str]) -> Dict[str, Dict]:
    """Analyze dependencies between boot files."""
    dependencies = {}
    
    for filename, content in boot_files.items():
        refs = extract_references(content)
        rules = extract_rules(content)
        concepts = extract_concepts(content)
        
        # Filter out self-references
        refs.discard(filename)
        
        dependencies[filename] = {
            "references": refs,
            "referenced_by": set(),
            "rules": rules,
            "concepts": concepts,
            "line_count": content.count('\n') + 1,
            "has_definitions": any(term in content.lower() for term in ["definition", "defined as", "means"]),
            "has_rules": len(rules) > 0,
            "has_examples": "example" in content.lower(),
        }
    
    # Build reverse references (who references me?)
    for filename, deps in dependencies.items():
        for ref in deps["references"]:
            if ref in dependencies:
                dependencies[ref]["referenced_by"].add(filename)
    
    return dependencies


def calculate_load_order(dependencies: Dict[str, Dict]) -> List[Tuple[str, int, str]]:
    """
    Calculate ideal load order based on dependencies.
    
    Returns list of (filename, priority, reason)
    """
    order = []
    
    # Phase 1: Files with no dependencies (foundations)
    for filename, deps in dependencies.items():
        if not deps["references"] and not deps["referenced_by"]:
            # Independent file
            if deps["has_definitions"]:
                order.append((filename, 1, "Foundation - defines concepts"))
            elif deps["has_rules"]:
                order.append((filename, 1, "Foundation - establishes rules"))
            else:
                order.append((filename, 1, "Foundation - independent"))
    
    # Phase 2: Files that define concepts (prerequisites)
    for filename, deps in dependencies.items():
        if deps["has_definitions"] and filename not in [o[0] for o in order]:
            if not deps["references"]:  # Doesn't depend on others
                order.append((filename, 2, "Prerequisite - defines concepts"))
    
    # Phase 3: Files that establish rules
    for filename, deps in dependencies.items():
        if deps["has_rules"] and filename not in [o[0] for o in order]:
            if all(ref in [o[0] for o in order] for ref in deps["references"]):
                order.append((filename, 3, "Rules - depends on definitions"))
    
    # Phase 4: Files with examples (applications)
    for filename, deps in dependencies.items():
        if deps["has_examples"] and filename not in [o[0] for o in order]:
            if all(ref in [o[0] for o in order] for ref in deps["references"]):
                order.append((filename, 4, "Application - uses rules and definitions"))
    
    # Phase 5: Remaining files
    for filename, deps in dependencies.items():
        if filename not in [o[0] for o in order]:
            if all(ref in [o[0] for o in order] for ref in deps["references"]):
                order.append((filename, 5, "Dependent - depends on loaded files"))
    
    # Phase 6: Any remaining (circular dependencies)
    for filename, deps in dependencies.items():
        if filename not in [o[0] for o in order]:
            order.append((filename, 6, "Circular dependency - load with caution"))
    
    return order


def evaluate_consistency(boot_files: Dict[str, str], dependencies: Dict[str, Dict]) -> Dict:
    """Evaluate logical consistency of boot files."""
    consistency = {
        "circular_dependencies": [],
        "missing_references": [],
        "rule_conflicts": [],
        "concept_coverage": {},
        "overall_score": 0
    }
    
    # Check for circular dependencies
    for filename, deps in dependencies.items():
        for ref in deps["references"]:
            if ref in dependencies:
                if filename in dependencies[ref]["references"]:
                    consistency["circular_dependencies"].append((filename, ref))
    
    # Check for missing references
    all_files = set(dependencies.keys())
    for filename, deps in dependencies.items():
        for ref in deps["references"]:
            if ref not in all_files:
                consistency["missing_references"].append((filename, ref))
    
    # Check for rule conflicts (simplified)
    all_rules = {}
    for filename, deps in dependencies.items():
        for rule in deps["rules"]:
            rule_id = rule.split(":")[0]
            if rule_id in all_rules:
                # Check if descriptions differ
                if all_rules[rule_id] != rule:
                    consistency["rule_conflicts"].append((rule_id, filename, all_rules[rule_id]))
            else:
                all_rules[rule_id] = rule
    
    # Calculate concept coverage
    all_concepts = set()
    for deps in dependencies.values():
        all_concepts.update(deps["concepts"])
    
    for concept in all_concepts:
        coverage = sum(1 for deps in dependencies.values() if concept in deps["concepts"])
        consistency["concept_coverage"][concept] = coverage
    
    # Calculate overall score
    total_issues = (len(consistency["circular_dependencies"]) + 
                   len(consistency["missing_references"]) + 
                   len(consistency["rule_conflicts"]))
    
    consistency["overall_score"] = max(0, 100 - (total_issues * 10))
    
    return consistency


def run_demo():
    """Run the demo."""
    print_header("DEMO: IDEAL BOOT LOADER ORDER")
    print(f"  Analyzing logical consistency of primer")
    print(f"  Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # Step 1: Load boot files
    print_section("Step 1: Load boot files")
    boot_files = load_boot_files()
    print_result("Files loaded", len(boot_files))
    for filename in boot_files:
        print_result(f"  {filename}", f"{boot_files[filename].count(chr(10)) + 1} lines")
    print_footer()
    
    # Step 2: Analyze dependencies
    print_section("Step 2: Analyze dependencies")
    dependencies = analyze_dependencies(boot_files)
    
    for filename, deps in dependencies.items():
        print_result(f"\n  {filename}", "")
        print_result("    References", ", ".join(deps["references"]) if deps["references"] else "None")
        print_result("    Referenced by", ", ".join(deps["referenced_by"]) if deps["referenced_by"] else "None")
        print_result("    Rules", len(deps["rules"]))
        print_result("    Concepts", len(deps["concepts"]))
        print_result("    Has definitions", "✓" if deps["has_definitions"] else "✗")
        print_result("    Has rules", "✓" if deps["has_rules"] else "✗")
        print_result("    Has examples", "✓" if deps["has_examples"] else "✗")
    print_footer()
    
    # Step 3: Calculate load order
    print_section("Step 3: Calculate ideal load order")
    load_order = calculate_load_order(dependencies)
    
    print("│  Priority | File | Reason")
    print("│  ─────────┼──────┼────────")
    for filename, priority, reason in sorted(load_order, key=lambda x: x[1]):
        print(f"│  {priority:<9} | {filename:<20} | {reason}")
    print_footer()
    
    # Step 4: Evaluate consistency
    print_section("Step 4: Evaluate logical consistency")
    consistency = evaluate_consistency(boot_files, dependencies)
    
    print_result("Overall consistency score", f"{consistency['overall_score']}%")
    print_result("Circular dependencies", len(consistency["circular_dependencies"]))
    print_result("Missing references", len(consistency["missing_references"]))
    print_result("Rule conflicts", len(consistency["rule_conflicts"]))
    
    if consistency["circular_dependencies"]:
        print_result("\n  Circular dependencies:", "")
        for file1, file2 in consistency["circular_dependencies"]:
            print_result(f"    {file1}", f"↔ {file2}")
    
    if consistency["missing_references"]:
        print_result("\n  Missing references:", "")
        for file1, file2 in consistency["missing_references"]:
            print_result(f"    {file1}", f"→ {file2}")
    
    if consistency["rule_conflicts"]:
        print_result("\n  Rule conflicts:", "")
        for rule_id, file1, desc in consistency["rule_conflicts"]:
            print_result(f"    {rule_id}", f"in {file1}: {desc[:50]}...")
    
    print_footer()
    
    # Step 5: Show dependency graph
    print_section("Step 5: Dependency graph (ASCII)")
    print("│")
    print("│  ┌─────────────────────────────────────────────────────────────┐")
    print("│  │                    BOOT DEPENDENCY GRAPH                   │")
    print("│  └─────────────────────────────────────────────────────────────┘")
    print("│")
    
    # Simple ASCII visualization
    for filename, priority, reason in sorted(load_order, key=lambda x: x[1]):
        deps = dependencies[filename]
        refs = ", ".join(deps["references"]) if deps["references"] else "none"
        print(f"│  {filename:<25} → [{refs}]")
    
    print("│")
    print_footer()
    
    # Step 6: Recommendation
    print_section("Step 6: Recommendation")
    print("│")
    print("│  IDEAL BOOT ORDER:")
    print("│")
    
    for i, (filename, priority, reason) in enumerate(sorted(load_order, key=lambda x: x[1]), 1):
        print(f"│  {i}. {filename}")
        print(f"│     └─ {reason}")
    
    print("│")
    print("│  NOTES:")
    print("│  - Load foundations first (no dependencies)")
    print("│  - Then prerequisites (define concepts)")
    print("│  - Then rules (depend on definitions)")
    print("│  - Then applications (use rules)")
    print("│  - Last: files with circular dependencies")
    print("│")
    print_footer()
    
    print_header("DEMO COMPLETE")
    print("  The socratic engine analyzed the boot files and determined")
    print("  the ideal loading order based on logical dependencies.")
    print()


def main():
    """Run demo."""
    run_demo()


if __name__ == "__main__":
    main()
