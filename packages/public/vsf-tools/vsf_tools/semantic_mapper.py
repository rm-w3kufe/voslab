"""semantic_mapper.py — Maps abstract predicates to semantic names.

Ported from child/scripts/semantic_mapper.py.
Transforms abstract predicates to include semantic metadata
that anchors symbols to real domain meaning.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


# Default glossary structure
DEFAULT_GLOSSARY = {
    "predicate_semantics": {
        "TRUE": {
            "real_name": "always_true",
            "description": "Condicion siempre verdadera - fallback",
            "domain": "control_flow",
        },
        "FALSE": {
            "real_name": "always_false",
            "description": "Condicion siempre falsa - fallback",
            "domain": "control_flow",
        },
    },
    "field_semantics": {
        "nats_reachable": {
            "real_name": "nats_connection",
            "description": "NATS server reachable",
            "domain": "infrastructure",
            "type": "boolean",
            "unit": "bool",
        },
        "disk_ok": {
            "real_name": "disk_health",
            "description": "Disk space within limits",
            "domain": "health",
            "type": "boolean",
            "unit": "bool",
        },
        "trust_level": {
            "real_name": "system_trust",
            "description": "Current trust level",
            "domain": "governance",
            "type": "float",
            "unit": "0-1",
            "interpretation": {
                "high": "> 0.8",
                "medium": "0.5-0.8",
                "low": "< 0.5",
            },
        },
    },
}


class SemanticMapper:
    """Maps predicates to semantic meanings."""
    
    def __init__(self, glossary_path: str | Path | None = None):
        """Initialize semantic mapper.
        
        Args:
            glossary_path: Path to semantic glossary JSON file
        """
        self.glossary = self._load_glossary(glossary_path)
    
    def _load_glossary(self, glossary_path: str | Path | None) -> Dict[str, Any]:
        """Load glossary from file or use default."""
        if glossary_path and Path(glossary_path).exists():
            with open(glossary_path) as f:
                return json.load(f)
        return DEFAULT_GLOSSARY
    
    def map_predicate(self, condition: str) -> Dict[str, Any]:
        """Map abstract predicate to semantic meaning.
        
        Args:
            condition: Abstract predicate string (e.g., "ctx_equals($ctx, 'trust_level', 0.8)")
            
        Returns:
            Dict with semantic metadata
        """
        pred_semantics = self.glossary.get("predicate_semantics", {})
        
        # Direct match
        if condition in pred_semantics:
            return pred_semantics[condition]
        
        # Pattern match for ctx_equals
        if "ctx_equals" in condition:
            return self._map_ctx_equals(condition)
        
        # Pattern match for ctx_has
        if "ctx_has" in condition:
            return self._map_ctx_has(condition)
        
        # Pattern match for service_active
        if "service_active" in condition:
            return self._map_service_active(condition)
        
        # Default fallback
        return {
            "real_name": f"unknown_{condition[:20]}",
            "description": f"Unknown predicate: {condition}",
            "domain": "unknown",
            "original": condition,
        }
    
    def _map_ctx_equals(self, condition: str) -> Dict[str, Any]:
        """Map ctx_equals predicate."""
        field_semantics = self.glossary.get("field_semantics", {})
        
        try:
            # Extract field and value from ctx_equals($ctx, 'field', 'value')
            parts = condition.replace("ctx_equals($ctx, '", "").replace("')", "").split("', ")
            field = parts[0].strip("'")
            value = parts[1].strip("'") if len(parts) > 1 else ""
            
            field_sem = field_semantics.get(field, {})
            return {
                "real_name": f"{field_sem.get('real_name', field)}_{value}",
                "description": f"Condition: {field_sem.get('description', field)} == {value}",
                "domain": field_sem.get("domain", "unknown"),
                "field_original": field,
                "threshold_value": value,
                "field_description": field_sem.get("description", ""),
                "unit": field_sem.get("unit", ""),
                "interpretation": field_sem.get("interpretation", {}),
            }
        except Exception:
            return {
                "real_name": f"ctx_equals_unknown",
                "description": f"Malformed ctx_equals: {condition}",
                "domain": "unknown",
                "original": condition,
            }
    
    def _map_ctx_has(self, condition: str) -> Dict[str, Any]:
        """Map ctx_has predicate."""
        field_semantics = self.glossary.get("field_semantics", {})
        
        try:
            # Extract field from ctx_has($ctx, 'field')
            field = condition.replace("ctx_has($ctx, '", "").replace("')", "")
            field_sem = field_semantics.get(field, {})
            return {
                "real_name": f"{field_sem.get('real_name', field)}_exists",
                "description": f"Check existence: {field_sem.get('description', field)}",
                "domain": field_sem.get("domain", "unknown"),
                "field_original": field,
                "field_description": field_sem.get("description", ""),
                "type": field_sem.get("type", "unknown"),
            }
        except Exception:
            return {
                "real_name": f"ctx_has_unknown",
                "description": f"Malformed ctx_has: {condition}",
                "domain": "unknown",
                "original": condition,
            }
    
    def _map_service_active(self, condition: str) -> Dict[str, Any]:
        """Map service_active predicate."""
        try:
            # Extract service name from service_active('service_name')
            service = condition.replace("service_active('", "").replace("')", "")
            return {
                "real_name": f"service_{service}_active",
                "description": f"Check if service '{service}' is active",
                "domain": "infrastructure",
                "service": service,
                "type": "boolean",
            }
        except Exception:
            return {
                "real_name": "service_active_unknown",
                "description": f"Malformed service_active: {condition}",
                "domain": "unknown",
                "original": condition,
            }
    
    def map_forest(self, forest: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        """Map a forest of predicates to semantic meanings.
        
        Args:
            forest: List of predicate trees
            
        Returns:
            List of trees with semantic metadata added
        """
        result = []
        for tree in forest:
            mapped_tree = self._map_tree(tree)
            result.append(mapped_tree)
        return result
    
    def _map_tree(self, tree: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively map a tree to add semantic metadata."""
        if not isinstance(tree, dict):
            return tree
        
        result = dict(tree)
        
        # Map condition if present
        if "condition" in result:
            result["semantics"] = self.map_predicate(result["condition"])
        
        # Recursively map children
        if "children" in result:
            result["children"] = [self._map_tree(child) for child in result["children"]]
        
        if "true_branch" in result:
            result["true_branch"] = self._map_tree(result["true_branch"])
        
        if "false_branch" in result:
            result["false_branch"] = self._map_tree(result["false_branch"])
        
        return result


# Convenience functions
def map_predicate(condition: str, glossary_path: str | Path | None = None) -> Dict[str, Any]:
    """Map a single predicate to semantic meaning."""
    mapper = SemanticMapper(glossary_path)
    return mapper.map_predicate(condition)


def map_forest(forest: list[Dict[str, Any]], glossary_path: str | Path | None = None) -> list[Dict[str, Any]]:
    """Map a forest of predicates to semantic meanings."""
    mapper = SemanticMapper(glossary_path)
    return mapper.map_forest(forest)
