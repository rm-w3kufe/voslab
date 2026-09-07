"""tests/test_semantic_mapper.py — Tests for semantic mapper."""

import pytest
from vsf_tools.semantic_mapper import SemanticMapper, map_predicate, map_forest


class TestSemanticMapper:
    def test_map_true(self):
        mapper = SemanticMapper()
        result = mapper.map_predicate("TRUE")
        assert result["real_name"] == "always_true"
        assert result["domain"] == "control_flow"
    
    def test_map_false(self):
        mapper = SemanticMapper()
        result = mapper.map_predicate("FALSE")
        assert result["real_name"] == "always_false"
    
    def test_map_ctx_equals(self):
        mapper = SemanticMapper()
        result = mapper.map_predicate("ctx_equals($ctx, 'trust_level', '0.8')")
        assert "trust" in result["real_name"].lower()
        assert result["threshold_value"] == "0.8"
    
    def test_map_ctx_has(self):
        mapper = SemanticMapper()
        result = mapper.map_predicate("ctx_has($ctx, 'nats_reachable')")
        assert "nats" in result["real_name"].lower()
        assert result["type"] == "boolean"
    
    def test_map_service_active(self):
        mapper = SemanticMapper()
        result = mapper.map_predicate("service_active('nats')")
        assert "nats" in result["real_name"].lower()
        assert result["service"] == "nats"
    
    def test_map_unknown(self):
        mapper = SemanticMapper()
        result = mapper.map_predicate("unknown_predicate")
        assert result["domain"] == "unknown"
    
    def test_map_forest(self):
        mapper = SemanticMapper()
        forest = [
            {"condition": "TRUE", "value": 1},
            {"condition": "ctx_has($ctx, 'disk_ok')", "value": 0},
        ]
        result = mapper.map_forest(forest)
        assert len(result) == 2
        assert "semantics" in result[0]
        assert "semantics" in result[1]


class TestConvenienceFunctions:
    def test_map_predicate(self):
        result = map_predicate("TRUE")
        assert result["real_name"] == "always_true"
    
    def test_map_forest(self):
        forest = [{"condition": "TRUE"}]
        result = map_forest(forest)
        assert len(result) == 1
