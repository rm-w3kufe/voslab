"""tokenizer.py — Simple tokenizer for VSM documents.

This is a minimal tokenizer for opencode's token counting needs.
It provides a basic tokenize function that counts words/tokens.
"""

from __future__ import annotations

import re
from typing import List


def tokenize(text: str) -> List[str]:
    """Tokenize text into words/tokens.
    
    Args:
        text: Input text to tokenize
        
    Returns:
        List of tokens
    """
    if not text:
        return []
    
    # Simple word tokenization
    # Split on whitespace and punctuation
    tokens = re.findall(r'\b\w+\b', text)
    return tokens


def count_tokens(text: str) -> int:
    """Count tokens in text.
    
    Args:
        text: Input text to count tokens in
        
    Returns:
        Number of tokens
    """
    return len(tokenize(text))
