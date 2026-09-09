"""vsf-ontology — Document and script ontology predicates.

Ported from child/scripts/vsl/classifier/vsf_hooks_predicates.py
18 predicates for document analysis, script analysis, staging, and versioning.
"""

__version__ = "0.1.0"

# Key exports for common usage
from .doc_predicates import is_valid_document, classify_document
from .script_predicates import is_valid_script, classify_script
from .security_predicates import check_security, validate_permissions
from .staging_predicates import is_staged, validate_staging

__all__ = [
    "is_valid_document",
    "classify_document",
    "is_valid_script",
    "classify_script",
    "check_security",
    "validate_permissions",
    "is_staged",
    "validate_staging",
]
