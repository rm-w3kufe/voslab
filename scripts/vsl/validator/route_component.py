#!/usr/bin/env python3
"""
route_component.py — Automated routing decision for new components.

Determines whether a new script/plugin should go to:
- socratic-engine (domain-agnostic)
- vsf_script (VSF-specific)
- opencode_plugin (enforcement at write-time)
- docs_spec_revision (documentation)

Usage:
    python3 scripts/vsl/validator/route_component.py <component_path>
    python3 scripts/vsl/validator/route_component.py --analyze <component_name> --type <script|plugin|doc>
"""

import sys
import re
from pathlib import Path
from typing import Tuple, Dict, List


def find_repo_root() -> Path:
    """Find the repository root."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / '.git').exists():
            return current
        current = current.parent
    return Path.cwd()


def analyze_domain_specificity(content: str) -> Tuple[bool, str]:
    """Check if component is domain-agnostic."""
    # VSF-specific patterns (strong indicators)
    vsf_patterns = [
        r'docs/spec_revision',
        r'system/',
        r'boot/',
        r's5-policy',
        r'instance\.vsm',
        r'@var',
        r'binding',
        r'vsf',
        r'vsl',
    ]
    
    # General patterns (weak indicators - need multiple)
    general_patterns = [
        r'epistemic',
        r'certainty',
        r'veracity',
        r'drift.*detection',
        r'predicate.*general',
        r'multi.*bridge',
    ]
    
    # Count patterns (VSF patterns are stronger)
    vsf_count = sum(1 for p in vsf_patterns if re.search(p, content, re.IGNORECASE))
    general_count = sum(1 for p in general_patterns if re.search(p, content, re.IGNORECASE))
    
    # Need multiple general patterns to classify as domain-agnostic
    if general_count >= 2 and vsf_count == 0:
        return True, "Domain-agnostic (multiple general patterns, no VSF patterns)"
    else:
        return False, f"VSF-specific (VSF: {vsf_count}, General: {general_count})"


def analyze_enforcement_needs(content: str) -> Tuple[bool, str]:
    """Check if component needs write-time enforcement."""
    # Only detect actual enforcement usage, not string literals
    enforcement_patterns = [
        r'throw\s+new\s+Error',
        r'reject\s*\(',
        r'process\.exit\s*\(\s*1\s*\)',
        r'BLOCKING\s+on',
        r'blocking\s*:',
    ]
    
    count = sum(1 for p in enforcement_patterns if re.search(p, content, re.IGNORECASE))
    
    if count > 0:
        return True, f"Needs enforcement ({count} patterns found)"
    else:
        return False, "No enforcement patterns found"


def analyze_opencode_lifecycle(content: str) -> Tuple[bool, str]:
    """Check if component uses opencode lifecycle."""
    # Actual opencode lifecycle patterns (used in plugins)
    lifecycle_patterns = [
        r'tool\.execute\.after',
        r'tool\.execute\.before',
        r'tool\.execute',
        r'session\.created',
        r'session\.idle',
        r'input\.tool\s*===',
        r'input\.tool\s*!==',
    ]
    
    count = sum(1 for p in lifecycle_patterns if re.search(p, content, re.IGNORECASE))
    
    if count > 0:
        return True, f"Uses opencode lifecycle ({count} patterns found)"
    else:
        return False, "No opencode lifecycle patterns"


def analyze_documentation(content: str) -> Tuple[bool, str]:
    """Check if component is documentation."""
    # Documentation must start with VSL header
    has_header = re.search(r'⟦.*\|.*-v\d+\|.*⟧', content)
    
    # Documentation patterns (must have header to count)
    doc_patterns = [
        r'^@status\s+(proposed|active|ratified|archived)',
        r'^@vsm\s+\d+\.\d+',
        r'policy:',
        r'rules:',
        r'specification:',
    ]
    
    count = sum(1 for p in doc_patterns if re.search(p, content, re.MULTILINE))
    
    if has_header and count >= 2:
        return True, f"Documentation (VSL header + {count} patterns)"
    else:
        return False, "Not documentation"


def route_component(component_path: Path) -> Dict:
    """Route a component to its appropriate destination."""
    if not component_path.exists():
        return {"error": f"Component not found: {component_path}"}
    
    content = component_path.read_text(encoding='utf-8')
    filename = component_path.name
    
    # Analyze
    is_domain_agnostic, domain_reason = analyze_domain_specificity(content)
    needs_enforcement, enforcement_reason = analyze_enforcement_needs(content)
    uses_lifecycle, lifecycle_reason = analyze_opencode_lifecycle(content)
    is_documentation, doc_reason = analyze_documentation(content)
    
    # Decision tree
    if is_domain_agnostic:
        destination = "socratic-engine"
        reason = domain_reason
        repository = "~/socratic-engine/"
    elif needs_enforcement and uses_lifecycle:
        destination = "opencode_plugin"
        reason = lifecycle_reason
        repository = "~/vsf/.opencode/plugins/"
    elif needs_enforcement:
        destination = "script_with_enforcement"
        reason = enforcement_reason
        repository = "~/vsf/scripts/vsl/"
    elif is_documentation:
        destination = "docs_spec_revision"
        reason = doc_reason
        repository = "~/vsf/docs/spec_revision/"
    else:
        destination = "vsf_script"
        reason = "VSF-specific script"
        repository = "~/vsf/scripts/vsl/"
    
    return {
        "component": filename,
        "destination": destination,
        "reason": reason,
        "repository": repository,
        "analysis": {
            "domain_agnostic": is_domain_agnostic,
            "domain_reason": domain_reason,
            "needs_enforcement": needs_enforcement,
            "enforcement_reason": enforcement_reason,
            "uses_lifecycle": uses_lifecycle,
            "lifecycle_reason": lifecycle_reason,
            "is_documentation": is_documentation,
            "doc_reason": doc_reason,
        }
    }


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Route component to appropriate destination')
    parser.add_argument('component', help='Component path or name')
    parser.add_argument('--analyze', action='store_true', help='Analyze component')
    parser.add_argument('--type', choices=['script', 'plugin', 'doc'], help='Component type')
    
    args = parser.parse_args()
    
    component_path = Path(args.component)
    
    if args.analyze:
        # Analyze component
        result = route_component(component_path)
        
        if "error" in result:
            print(f"❌ {result['error']}")
            return 1
        
        print(f"\n{'='*60}")
        print(f"ROUTING DECISION: {result['component']}")
        print(f"{'='*60}\n")
        
        print(f"📍 DESTINATION: {result['destination']}")
        print(f"📁 REPOSITORY: {result['repository']}")
        print(f"📝 REASON: {result['reason']}\n")
        
        print("📊 ANALYSIS:")
        for key, value in result['analysis'].items():
            if 'reason' in key:
                continue
            reason_key = key.replace('_', '_reason')
            if reason_key in result['analysis']:
                print(f"  {key}: {value} — {result['analysis'][reason_key]}")
            else:
                print(f"  {key}: {value}")
        
        print(f"\n{'='*60}")
        
        return 0
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
