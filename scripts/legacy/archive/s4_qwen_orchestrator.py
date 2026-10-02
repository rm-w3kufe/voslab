#!/usr/bin/env python3
"""
S4 Orchestrator — Qwen2.5-coder Edition
Runs on Ollama (LXC 101) — fully autonomous LLM intelligence without Claude dependency

Reads: BBS system-state
Analyzes: via Qwen2.5-coder local LLM
Publishes: s4-analysis decisions back to BBS
"""

import requests
import json
import time
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BBS_URL = "http://10.10.20.20:8600"  # LXC 106 BBS
OLLAMA_URL = "http://127.0.0.1:11434"  # Local Ollama on LXC 101
MODEL = "qwen2.5-coder:7b"


class S4QwenOrchestrator:
    """S4 Intelligence Layer using Qwen2.5-coder LLM (fully autonomous)"""

    def __init__(self):
        self.state = {}
        self.decisions = []
        logger.info("S4 Qwen Orchestrator initialized (LLM-powered)")

    def read_system_state(self):
        """Read latest system-state from BBS"""
        try:
            r = requests.get(f"{BBS_URL}/api/state/current", timeout=5)
            if r.status_code == 200:
                result = r.json()
                if "state" in result:
                    self.state = result["state"]
                    logger.info(
                        f"✓ System state read: node={self.state.get('node')}, "
                        f"ram_alloc={self.state.get('hardware', {}).get('ram_allocated_gb')}GB"
                    )
                    return True
        except Exception as e:
            logger.warning(f"Failed to read BBS state: {e}")
        return False

    def analyze_state_with_qwen(self):
        """Use Qwen2.5-coder to analyze system state and generate decisions"""
        if not self.state:
            logger.warning("No state available for analysis")
            return []

        hardware = self.state.get("hardware", {})
        containers = self.state.get("containers", {})

        # Build concise context for Qwen (shorter for faster inference)
        ram_pct = int((hardware.get('ram_allocated_gb', 0) / 24) * 100)
        disk_pct = int((hardware.get('disk_used_gb', 0) / 94) * 100)
        unhealthy = [name for name, info in containers.items() if info.get("status") != "running"]

        state_summary = (
            f"System Health Check: RAM {hardware.get('ram_allocated_gb')}GB out of 24GB, "
            f"Disk {disk_pct}% full, {len(unhealthy)} containers down. "
            f"Generate 1-2 JSON decisions for infrastructure governance. "
            f"Return only valid JSON array with decision_type, action, target, reason fields."
        )

        try:
            # Call Ollama /api/generate endpoint (native, not OpenAI-compat)
            logger.info(f"Calling Ollama {MODEL} at {OLLAMA_URL}/api/generate...")
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": MODEL,
                    "prompt": state_summary,
                    "stream": False,
                    "temperature": 0.5,
                },
                timeout=120,  # Extended: Qwen2.5-coder:7b is slow (120s for inference)
            )

            logger.info(f"Ollama response: HTTP {resp.status_code}")
            if resp.status_code == 200:
                result = resp.json()
                response_text = result.get("response", "")

                # Strip markdown code fences if present (Qwen wraps JSON in ```json...```)
                if response_text.startswith("```"):
                    response_text = response_text.split("```")[1]  # Extract content between fences
                    if response_text.startswith("json\n"):
                        response_text = response_text[5:]  # Remove "json\n" prefix
                    response_text = response_text.strip()

                # Parse JSON from response
                try:
                    decisions = json.loads(response_text)
                    if isinstance(decisions, list):
                        logger.info(f"✓ Qwen generated {len(decisions)} decisions")
                        return decisions
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse Qwen response as JSON: {str(e)[:100]} | Response: {response_text[:150]}")
                    return []

        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Ollama unreachable at {OLLAMA_URL}: {e}")
        except requests.exceptions.Timeout as e:
            logger.warning(f"Ollama timeout (60s exceeded): {e}")
        except Exception as e:
            logger.error(f"Qwen analysis error ({type(e).__name__}): {e}")

        return []

    def publish_decisions(self):
        """Publish S4 analysis and recommendations back to BBS"""
        if not self.decisions:
            return

        message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "s4_qwen",
            "topic": "s4-analysis",
            "priority": "info",
            "ttl": 86400,
            "payload": {
                "analysis_type": "qwen_lm_analysis",
                "timestamp": datetime.utcnow().isoformat(),
                "decisions": self.decisions,
                "state_digest": {
                    "node": self.state.get("node"),
                    "ram_gb": self.state.get("hardware", {}).get("ram_allocated_gb"),
                    "containers": len(self.state.get("containers", {}))
                },
                "llm_model": MODEL,
            }
        }

        try:
            r = requests.post(f"{BBS_URL}/api/message", json=message, timeout=5)
            if r.status_code == 200:
                result = r.json()
                logger.info(f"✓ Qwen decisions published to BBS (msg_id={result.get('id')})")
                return True
        except Exception as e:
            logger.warning(f"Failed to publish decisions: {e}")

        return False

    def run_once(self):
        """Single orchestration cycle"""
        logger.info("=" * 60)
        logger.info("S4 QWEN ORCHESTRATION CYCLE (LLM-powered)")
        logger.info("=" * 60)

        # 1. Read state from BBS
        if not self.read_system_state():
            logger.warning("No system state available")
            return

        # 2. Analyze with Qwen LLM
        self.decisions = self.analyze_state_with_qwen()

        # 3. Publish recommendations back to BBS
        if self.decisions:
            self.publish_decisions()
        else:
            logger.info("No decisions generated")

        logger.info("Cycle complete\n")

    def run_continuous(self, interval=300):
        """Run orchestration every N seconds"""
        logger.info(f"Starting continuous Qwen mode (interval={interval}s)")
        logger.info(f"LLM: {MODEL} on Ollama at {OLLAMA_URL}")
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Error in cycle: {e}")
            time.sleep(interval)


if __name__ == "__main__":
    s4 = S4QwenOrchestrator()

    # For testing: run once
    # s4.run_once()

    # For production: run continuously
    s4.run_continuous(interval=300)  # Every 5 minutes
