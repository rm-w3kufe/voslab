#!/usr/bin/env python3
"""
qwen_mermaid_view — view-module #5: Qwen → Mermaid diagram generator.

Takes a natural-language description, calls Qwen (Ollama on LXC 110) with a
VSM-aware system prompt, and returns valid Mermaid flowchart code.

CONSTRAINTS (Ollama 0.21.2, qwen2.5-coder:1.5b, CPU-only, 4GB RAM):
  - Inference speed: ~1.3 tok/s (CPU)
  - Stable context: num_ctx=256 only (larger contexts crash on this version)
  - System prompt + user input must fit in ~256 tokens
  - Runner KV cache can corrupt after some requests → auto-restart on 500
  - Typical response time: 60-150s for a simple diagram

Stdlib-only: urllib.request for HTTP, json for parsing.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

MODULE_ID = "qwen-mermaid"
SYSTEM_ID = "alpha"
SCHEMA = "qwen-mermaid-view/0.1"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.10.20.110:11434")
MODEL = os.environ.get("QWEN_MODEL", "qwen2.5-coder:1.5b")
TIMEOUT = int(os.environ.get("QWEN_TIMEOUT", "180"))
OLLAMA_RESTART_CMD = os.environ.get("OLLAMA_RESTART_CMD", "systemctl restart ollama")

# ── In-memory cache ───────────────────────────────────────────────────────────
_cache = {}  # description_hash -> {mermaid, timestamp}
MAX_CACHE = 16
CACHE_TTL = 3600  # seconds

# ── System prompt (must fit in ~256 tokens with user input) ───────────────────
SYSTEM_PROMPT = """Generate Mermaid flowchart TB. VSM: S5 S4 S3 S2 S1 S3*. Dotted audit edges. Only mermaid code.

User description: """


def _cache_key(desc):
    return str(hash(desc.strip().lower()))[-12:]


def _cached(desc):
    k = _cache_key(desc)
    entry = _cache.get(k)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["mermaid"]
    return None


def _cache_set(desc, mermaid):
    k = _cache_key(desc)
    _cache[k] = {"mermaid": mermaid, "ts": time.time()}
    if len(_cache) > MAX_CACHE:
        # Remove oldest
        oldest = min(_cache.keys(), key=lambda x: _cache[x]["ts"])
        del _cache[oldest]


def _strip_markdown_fences(raw):
    """Remove markdown code fences and mermaid preamble from the output."""
    # Remove ```mermaid ... ``` fences
    if "```" in raw:
        parts = raw.split("```")
        for i in range(1, len(parts), 2):
            content = parts[i].strip()
            if content:
                raw = content
                break

    # Remove leading "mermaid" line (not part of mermaid syntax)
    lines = raw.split("\n")
    while lines and lines[0].strip().lower() in ("mermaid",):
        lines = lines[1:]
    raw = "\n".join(lines).strip()

    return raw


def _restart_ollama():
    """Restart the Ollama service to clear corrupted KV cache state."""
    try:
        subprocess.run(
            OLLAMA_RESTART_CMD.split(),
            timeout=15,
            capture_output=True,
        )
        time.sleep(3)  # wait for service to come up
        return True
    except Exception:
        return False


def generate(description):
    """Send a natural-language description to Qwen and return Mermaid code.

    Returns dict: {ok: bool, mermaid: str, error: str?}
    """
    if not description or not description.strip():
        return {"ok": False, "mermaid": "", "error": "Description is empty"}

    # Check cache first
    cached = _cached(description)
    if cached is not None:
        return {"ok": True, "mermaid": cached, "error": None, "cached": True}

    desc = description.strip()
    # Truncate user description to prevent context overflow
    if len(desc) > 150:
        desc = desc[:150]

    prompt = SYSTEM_PROMPT + desc

    payload = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 80,
            "num_ctx": 256,  # must be 256 — larger contexts crash Ollama 0.21.2
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    # Try up to 2 times — once, and once after restart if first attempt gets 500
    for attempt in range(2):
        try:
            resp = urllib.request.urlopen(req, timeout=TIMEOUT)
            body = json.loads(resp.read().decode("utf-8"))
            raw = body.get("response", "").strip()
        except urllib.error.HTTPError as e:
            if e.code == 500 and attempt == 0:
                # Restart Ollama and retry (KV cache corruption)
                _restart_ollama()
                continue
            return {"ok": False, "mermaid": "", "error": f"Ollama HTTP {e.code}: {e.reason}"}
        except urllib.error.URLError as e:
            if attempt == 0:
                _restart_ollama()
                continue
            return {"ok": False, "mermaid": "", "error": f"Ollama unreachable: {e.reason}"}
        except Exception as e:
            if attempt == 0:
                _restart_ollama()
                continue
            return {"ok": False, "mermaid": "", "error": str(e)}

        # Process the response
        raw = _strip_markdown_fences(raw)
        raw = raw.strip()

        if not raw:
            return {"ok": False, "mermaid": "", "error": "Empty response from Qwen"}

        # Basic validation
        if not any(kw in raw for kw in
                   ["flowchart", "sequenceDiagram", "stateDiagram", "graph "]):
            # The response might still be useful — return it with a warning
            return {"ok": True, "mermaid": raw,
                    "error": None, "note": "response may not be valid Mermaid"}

        # Cache and return
        _cache_set(description, raw)
        return {"ok": True, "mermaid": raw, "error": None}

    return {"ok": False, "mermaid": "", "error": "Generation failed after Ollama restart"}


def check_status():
    """Probe Ollama reachability and return model info."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        body = json.loads(resp.read().decode("utf-8"))
        models = [m["name"] for m in body.get("models", [])]
        has_model = MODEL in models
        available = models[:5]
        return {
            "ok": True,
            "model": MODEL if has_model else (available[0] if available else "none"),
            "model_loaded": has_model,
            "available": available,
            "ollama_url": OLLAMA_URL,
            "note": "CPU-only, ~1.3 tok/s. Expect 60-150s per diagram.",
            "error": None,
        }
    except urllib.error.URLError as e:
        return {"ok": False, "model": MODEL, "error": f"Ollama unreachable at {OLLAMA_URL}: {e.reason}"}
    except Exception as e:
        return {"ok": False, "model": MODEL, "error": str(e)}


def build_tick():
    """Return a tick dict for the view-module protocol (live status)."""
    cache_size = len(_cache)
    return {
        "module_id": MODULE_ID,
        "schema": SCHEMA,
        "system_id": SYSTEM_ID,
        "status": "idle",
        "model": MODEL,
        "ollama_url": OLLAMA_URL,
        "cache_entries": cache_size,
        "note": "POST /api/qwen-mermaid with {'description': '...'} to generate",
        "certified": False,
    }
