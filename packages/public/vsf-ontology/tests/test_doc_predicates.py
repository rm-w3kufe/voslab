"""tests/test_doc_predicates.py — Tests for document predicates."""

import tempfile
import os
from pathlib import Path

import pytest
from vsf_ontology.doc_predicates import (
    doc_extract_topic,
    doc_search_existing,
    doc_topic_exact_match,
    doc_topic_partial_match,
    doc_has_content,
    has_duplicates,
    is_source,
    is_reference,
    high_overlap,
    low_overlap,
    is_doc_about_doc,
    doc_analyze,
    doc_classify,
    classification_equals,
    no_match_found,
    doc_duplicate_check,
    doc_exact_duplicate,
    doc_snowball_check,
)


class TestDocExtractTopic:
    def test_empty(self):
        assert doc_extract_topic("") == ""

    def test_none(self):
        assert doc_extract_topic(None) == ""

    def test_header(self):
        content = "⟦ my_topic | TYPE-v1 | vsm-1.2 | 2026-01-01T00:00:00Z ⟧"
        assert doc_extract_topic(content) == "my_topic"

    def test_first_line(self):
        content = "// comment\nThis is the topic"
        assert doc_extract_topic(content) == "This is the topic"


class TestDocSearchExisting:
    def test_empty_topic(self):
        assert doc_search_existing("") == []

    def test_no_matches(self):
        assert doc_search_existing("nonexistent_topic_xyz") == []


class TestDocTopicExactMatch:
    def test_true(self):
        assert doc_topic_exact_match(["file.vsm"]) is True

    def test_false(self):
        assert doc_topic_exact_match([]) is False


class TestDocTopicPartialMatch:
    def test_above_threshold(self):
        assert doc_topic_partial_match([0.8, 0.5]) is True

    def test_below_threshold(self):
        assert doc_topic_partial_match([0.3, 0.2]) is False

    def test_single_value(self):
        assert doc_topic_partial_match(0.9) is True


class TestDocHasContent:
    def test_empty(self):
        assert doc_has_content("") is False

    def test_none(self):
        assert doc_has_content(None) is False

    def test_comments_only(self):
        assert doc_has_content("// comment\n// another") is False

    def test_real_content(self):
        assert doc_has_content("// comment\nLine 1\nLine 2\nLine 3") is True


class TestHasDuplicates:
    def test_single(self):
        assert has_duplicates(["one"]) is False

    def test_multiple(self):
        assert has_duplicates(["one", "two"]) is True


class TestIsSource:
    def test_fuente_path(self):
        assert is_source({"new_doc_path": "/docs/fuente/test.vsm"}) is True

    def test_ratified(self):
        assert is_source({"status": "ratified"}) is True

    def test_other(self):
        assert is_source({"status": "active"}) is False


class TestIsReference:
    def test_referencia_path(self):
        assert is_reference({"new_doc_path": "/docs/referencia/test.vsm"}) is True

    def test_reference_status(self):
        assert is_reference({"status": "reference"}) is True

    def test_other(self):
        assert is_reference({"status": "active"}) is False


class TestOverlap:
    def test_high(self):
        # 5 out of 6 words shared = Jaccard ~0.83
        assert high_overlap("a b c d e f", "a b c d e g") is True

    def test_low(self):
        # 0 out of 6 words shared = Jaccard 0.0
        assert low_overlap("a b c d e f", "g h i j k l") is True


class TestIsDocAboutDoc:
    def test_empty(self):
        assert is_doc_about_doc("") is False

    def test_normal_doc(self):
        assert is_doc_about_doc("This is about architecture.\nMany lines of content.") is False

    def test_snowball(self):
        content = "documento\n.vsm\neste documento\nel doc\n" + "\n".join(["line"] * 20)
        assert is_doc_about_doc(content) is True


class TestDocAnalyze:
    def test_analyze(self):
        result = doc_analyze("⟦ test | TYPE-v1 | vsm-1.2 | 2026-01-01T00:00:00Z ⟧\nLine 1\nLine 2")
        assert result["topic"] == "test"
        assert result["has_content"] is True
        assert result["is_about_doc"] is False
        assert result["size"] > 0


class TestDocClassify:
    def test_empty(self):
        assert doc_classify({"has_content": False}) == "EMPTY"

    def test_snowball(self):
        assert doc_classify({"has_content": True, "is_about_doc": True}) == "SNOWBALL"

    def test_content(self):
        assert doc_classify({"has_content": True, "is_about_doc": False, "topic": "test"}) == "CONTENT"


class TestClassificationEquals:
    def test_equal(self):
        assert classification_equals("CONTENT", "CONTENT") is True

    def test_not_equal(self):
        assert classification_equals("CONTENT", "EMPTY") is False


class TestNoMatchFound:
    def test_zero(self):
        assert no_match_found(0) is True

    def test_nonzero(self):
        assert no_match_found(1) is False


class TestDocDuplicateCheck:
    def test_no_match(self):
        assert doc_duplicate_check("⟦ nonexistent_xyz | TYPE-v1 | vsm-1.2 | 2026-01-01T00:00:00Z ⟧") is False


class TestDocSnowballCheck:
    def test_normal(self):
        assert doc_snowball_check("Normal document content") is False
