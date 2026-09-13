#!/usr/bin/env python3
"""parse_query_mcp.py — MCP server for query parsing.

This MCP server exposes a parse_query function that parses natural language
queries into socratic trees using a fast rule-based parser. Ollama is used
as fallback for edge cases only.

Usage:
  python3 parse_query_mcp.py

Architecture:
  Bridge → MCP Server → Rule-based (fast) → Ollama fallback (edge cases) → Socratic Tree
"""
from __future__ import annotations

import json
import re
import sys
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── Configuration ──────────────────────────────────────────────────────────────
VOSLAB_PATH = Path(os.environ.get("VOSLAB_PATH", Path(__file__).resolve().parent.parent.parent))
RSI_CYCLE_PATH = VOSLAB_PATH / "system" / "kernel" / "rsi_cycle.py"

OLLAMA_ENABLED = False  # set True to enable Ollama fallback for edge cases
OLLAMA_TIMEOUT = 2     # seconds for Ollama fallback
OLLAMA_MODEL = "qwen2.5:0.5b"
OLLAMA_API = "http://localhost:11434"
OLLAMA_COOLDOWN = 60   # seconds after Ollama failure before retry

# Available predicates for tree construction
AVAILABLE_PREDICATES = {
    "security": ["action_forbidden", "path_forbidden"],
    "state": ["task_has_work", "state_consistent", "task_active"],
    "quality": ["file_valid", "naming_conforms", "vsm_has_header"],
    "learning": ["not_redundant", "pattern_known"],
    "scripts": ["script_exists", "script_domain_ok", "script_call", "scripts_manifest",
                "state_scripts_ok", "vsl_scripts_ok", "audit_scripts_ok", "s1_kernel_scripts_ok"],
    "plugins": ["event_router_ok", "lifecycle_valid", "gap_free", "onboard_complete"],
    "child": ["hook_metrics_ok", "semantic_mapper_ok", "process_staging_ok", "load_hooks_ok"],
}

# ─── Entity Extraction ──────────────────────────────────────────────────────────

# Tool detection patterns
TOOL_PATTERNS = [
    (r'\b(edit|modify|change|update|replace)\b', 'edit'),
    (r'\b(read|show|display|cat|view|open)\b', 'read'),
    (r'\b(write|create|make|new|save)\b', 'write'),
    (r'\b(run|execute|bash|shell|command|script|npm|pip|git|docker|pct|curl)\b', 'bash'),
]

# Command extraction patterns
COMMAND_PATTERNS = [
    r'["\']([^"\']+)["\']',                    # quoted strings
    r'(?:run|execute|bash)\s+[:-]\s*(.+?)(?:\s*$|\s+and\b)',  # "run: cmd" or "execute: cmd"
    r'(rm\s+-rf\s+\S+)',                        # dangerous rm
    r'(sudo\s+\S+(?:\s+\S+)?)',                 # sudo commands
    r'(chmod\s+\S+\s+\S+)',                     # chmod
    r'(git\s+\S+(?:\s+\S+)?)',                  # git commands
    r'(docker\s+\S+(?:\s+\S+)?)',               # docker commands
    r'(pct\s+\S+(?:\s+\S+)?)',                  # proxmox commands
]

# File extraction patterns
FILE_PATTERNS = [
    r'(\S+\.(?:py|sh|vsm|json|ts|md|yaml|yml|toml|cfg|conf|rs))',  # common extensions
    r'((?:child|docs|scripts|src)/\S+)',          # path-like
    r'((?:~/|\./)\S+\.\S+)',                      # ~/path or ./path
]


def extract_entities(query: str, context: dict = None) -> dict:
    """Extract entities (command, file, tool) from query text."""
    context = context or {}
    query_lower = query.lower().strip()

    entities = {
        "command": context.get("command", ""),
        "file": context.get("file", ""),
        "tool": context.get("tool", ""),
    }

    # Extract tool (from context first, then pattern match)
    if not entities["tool"]:
        for pattern, tool in TOOL_PATTERNS:
            if re.search(pattern, query_lower):
                entities["tool"] = tool
                break
        if not entities["tool"]:
            entities["tool"] = "bash"  # default

    # Extract command (from context first, then pattern match)
    if not entities["command"]:
        for pattern in COMMAND_PATTERNS:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                entities["command"] = match.group(1) if match.lastindex else match.group(0)
                break

    # Extract file (from context first, then pattern match)
    if not entities["file"]:
        for pattern in FILE_PATTERNS:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                entities["file"] = match.group(1)
                break

    return entities


# ─── Intent Classification ──────────────────────────────────────────────────────

# Intent rules: (keywords, intent, required_predicates)
# Keywords are checked with OR logic (any match triggers the intent)
INTENT_RULES: List[Tuple[List[str], str, List[str]]] = [
    # Security
    (["forbidden", "blocked", "danger", "unsafe", "malicious", "attack", "vulnerability",
      "rm -rf", "chmod 777", "sudo rm", "rce", "injection", "exploit"],
     "security_check", ["action_forbidden", "path_forbidden"]),

    # Scripts
    (["script", "deploy", "manifest", "invoke", "call script", "run script"],
     "script_check", ["script_exists", "scripts_manifest"]),

    # State
    (["task", "backlog", "open task", "pending", "blocked", "what's next",
      "current state", "system state", "status"],
     "state_check", ["task_has_work", "state_consistent"]),

    # Plugins
    (["plugin", "event router", "lifecycle", "gap", "onboard", "hook event"],
     "plugin_check", ["event_router_ok", "lifecycle_valid"]),

    # Quality
    (["valid", "correct", "naming", "header", "format", "conforms", "lint",
      "syntax", "vsm valid", "well-formed"],
     "quality_check", ["file_valid", "naming_conforms"]),

    # Learning
    (["redundant", "duplicate", "repeat", "pattern", "learn", "memory",
      "scenario", "recall"],
     "learning_check", ["not_redundant", "pattern_known"]),

    # Hooks
    (["hook", "metric", "load hook", "hook metric", "semantic mapper"],
     "hook_check", ["hook_metrics_ok", "load_hooks_ok"]),

    # Check all
    (["everything", "all checks", "full audit", "complete check", "run all",
      "comprehensive", "health check"],
     "check_all", ["action_forbidden", "task_has_work", "event_router_ok", "scripts_manifest"]),
]


def classify_intent(query: str) -> Tuple[str, List[str]]:
    """Classify query intent using keyword matching. Returns (intent, predicates)."""
    query_lower = query.lower()

    # Score each intent by number of keyword matches
    best_intent = None
    best_score = 0
    best_preds = []

    for keywords, intent, predicates in INTENT_RULES:
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > best_score:
            best_score = score
            best_intent = intent
            best_preds = predicates

    if best_score > 0:
        return best_intent, best_preds

    return "unknown", []


# ─── Rule-Based Parser ──────────────────────────────────────────────────────────

def build_tree(intent: str, predicates: List[str], entities: dict) -> Optional[dict]:
    """Build a socratic tree from intent and entities."""
    if not predicates:
        return None

    children = []
    for pred in predicates:
        # Map predicate to appropriate args based on type
        if pred in ("action_forbidden",):
            children.append({
                "predicate": pred,
                "args": [entities["tool"], entities["file"]],
                "kwargs": {"command": entities["command"]},
            })
        elif pred in ("path_forbidden",):
            children.append({
                "predicate": pred,
                "args": [entities["file"]],
                "kwargs": {},
            })
        elif pred in ("script_exists",):
            children.append({
                "predicate": pred,
                "args": [entities["file"]],
                "kwargs": {},
            })
        elif pred in ("file_valid", "naming_conforms", "vsm_has_header"):
            children.append({
                "predicate": pred,
                "args": [entities["file"]],
                "kwargs": {},
            })
        elif pred in ("not_redundant",):
            children.append({
                "predicate": pred,
                "args": [entities["tool"], entities["file"], entities["command"]],
                "kwargs": {},
            })
        else:
            # Predicates with no args
            children.append({
                "predicate": pred,
                "args": [],
                "kwargs": {},
            })

    return {"op": "AND", "children": children}


def parse_with_rule_based(query: str, context: dict = None) -> dict:
    """Fast rule-based query parser."""
    entities = extract_entities(query, context)
    intent, predicates = classify_intent(query)
    tree = build_tree(intent, predicates, entities)

    return {
        "intent": intent,
        "entities": entities,
        "tree": tree,
    }


# ─── Ollama Fallback (edge cases only) ─────────────────────────────────────────

def check_ollama_available() -> bool:
    """Check if Ollama is responding (cached after first call, cooldown after failure)."""
    import time

    # Cooldown: if Ollama failed recently, don't retry
    if hasattr(check_ollama_available, "_failed_at"):
        elapsed = time.time() - check_ollama_available._failed_at
        if elapsed < OLLAMA_COOLDOWN:
            return False

    if not hasattr(check_ollama_available, "_cached"):
        try:
            req = urllib.request.Request(
                f"{OLLAMA_API}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())
                models = [m.get("name", "") for m in data.get("models", [])]
                check_ollama_available._cached = any("qwen" in m or "llama" in m for m in models)
        except Exception:
            check_ollama_available._cached = False

    return check_ollama_available._cached


PARSER_SYSTEM_PROMPT = """You are a query parser for a cybernetic control system.
Your ONLY job is to parse natural language queries into socratic trees (JSON).

Available predicates:
- Security: action_forbidden, path_forbidden
- State: task_has_work, state_consistent, task_active
- Quality: file_valid, naming_conforms, vsm_has_header
- Learning: not_redundant, pattern_known
- Scripts: script_exists, script_domain_ok, script_call, scripts_manifest
- Plugins: event_router_ok, lifecycle_valid, gap_free, onboard_complete
- Child: hook_metrics_ok, semantic_mapper_ok, process_staging_ok, load_hooks_ok

Output format (JSON only, no other text):
{"intent":"...","entities":{"command":"","file":"","tool":"bash"},"tree":{"op":"AND","children":[{"predicate":"...","args":[],"kwargs":{}}]}}

Rules:
1. ONLY respond with JSON, no other text
2. Extract commands from quotes or common patterns (rm, chmod, sudo)
3. Extract filenames (*.py, *.sh, *.vsm, etc.)
4. Choose predicates that match the query intent
5. If unsure, use check_all with basic predicates
"""


def parse_with_ollama(query: str) -> Optional[dict]:
    """Parse query using Ollama HTTP API (fast, 2s timeout)."""
    import time
    if not check_ollama_available():
        return None

    try:
        prompt = f"{PARSER_SYSTEM_PROMPT}\n\nQuery: {query}\n\nJSON:"
        payload = json.dumps({
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 200,
            }
        }).encode()

        req = urllib.request.Request(
            f"{OLLAMA_API}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            data = json.loads(resp.read())
            response = data.get("response", "")

            # Extract JSON from response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(response[start:end])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, Exception):
        # Mark Ollama as failed — cooldown prevents retries
        check_ollama_available._failed_at = time.time()
        check_ollama_available._cached = False

    return None


# ─── Main Parser (rule-based first, Ollama fallback) ────────────────────────────

def parse_query(query: str, context: dict = None) -> dict:
    """Parse a query: rule-based first (fast), Ollama fallback (edge cases).

    Returns: {"intent": str, "entities": dict, "tree": dict, "parsed": bool, "provider": str}
    """
    # Step 1: Rule-based (instant, handles 90%+ of queries)
    result = parse_with_rule_based(query, context)

    if result.get("tree") is not None:
        result["parsed"] = True
        result["provider"] = "rule-based"
        return result

    # Step 2: Ollama fallback for unknown intents (disabled by default)
    if OLLAMA_ENABLED and check_ollama_available():
        ollama_result = parse_with_ollama(query)
        if ollama_result and ollama_result.get("tree"):
            ollama_result["parsed"] = True
            ollama_result["provider"] = "ollama"
            return ollama_result

    # Step 3: Fallback to check_all (system always has something to evaluate)
    entities = result.get("entities", {})
    result["intent"] = "check_all"
    result["tree"] = {
        "op": "AND",
        "children": [
            {"predicate": "action_forbidden", "args": [entities.get("tool", "bash"), entities.get("file", "")], "kwargs": {"command": entities.get("command", "")}},
            {"predicate": "task_has_work", "args": [], "kwargs": {}},
            {"predicate": "event_router_ok", "args": [], "kwargs": {}},
            {"predicate": "scripts_manifest", "args": [], "kwargs": {}},
        ]
    }
    result["parsed"] = True
    result["provider"] = "rule-based"
    return result


# ─── MCP Server ─────────────────────────────────────────────────────────────────

def handle_mcp_request(request: dict) -> dict:
    """Handle MCP JSON-RPC request."""
    method = request.get("method")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        "listChanged": False
                    }
                },
                "serverInfo": {
                    "name": "parse-query-mcp",
                    "version": "2.0.0"
                }
            }
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "tools": [
                    {
                        "name": "parse_query",
                        "description": "Parse a natural language query into a socratic tree (rule-based, Ollama fallback)",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Natural language query to parse"
                                },
                                "context": {
                                    "type": "object",
                                    "description": "Optional context (command, file, tool)",
                                    "default": {}
                                }
                            },
                            "required": ["query"]
                        }
                    }
                ]
            }
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name == "parse_query":
            query = arguments.get("query", "")
            context = arguments.get("context", {})

            result = parse_query(query, context)

            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2)
                        }
                    ]
                }
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": -32601,
                    "message": f"Unknown tool: {tool_name}"
                }
            }

    else:
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {
                "code": -32601,
                "message": f"Unknown method: {method}"
            }
        }


def main():
    """Run MCP server on stdin/stdout."""
    for line in sys.stdin:
        try:
            request = json.loads(line.strip())
            response = handle_mcp_request(request)
            print(json.dumps(response))
            sys.stdout.flush()
        except json.JSONDecodeError:
            continue
        except Exception as e:
            print(json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }))
            sys.stdout.flush()


if __name__ == "__main__":
    main()
