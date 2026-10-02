#!/usr/bin/env python3
"""
qwen_client — direct HTTP transport to Ollama/Qwen on LXC 101 (10.10.20.10:11434).

Previous transport used SCP→pct push→pct exec because LXC 107 lacked firewall
access to LXC 101's ollama (vsf_llm chain, default-deny). Replaced by direct HTTP
after S3-granting 10.10.20.30 (LXC 107) access via llm_allow nftables set on LXC 101.
S3 grant: nft add element inet vsf_llm llm_allow { 10.10.20.30 }
  + persist /etc/nftables.d/vsf-llm.nft + coupling_registry state.db row updated.

API:
    import qwen_client
    text = qwen_client.generate('ep', prompt, num_predict=300, temperature=0.2)
    # → response text; '' or None = failure (already self-alerted to s5-alerts.db)

Callers: EP (vsl_run.py propose), SD (sd_digest.py). AC path is deterministic
(ac_classifier.py, D6') — no Qwen call there.
"""

import sys, os, json, subprocess, time
import urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s4_store
from s4_store import ALERTS_DIR, self_alert

MODEL = 'qwen2.5-coder:7b'
OLLAMA_URL = 'http://10.10.20.10:11434'  # LXC 101 VLAN20 direct (S3-granted, llm_allow)

RESTART_COOLDOWN_S = 600
RESTART_STAMP = os.path.join(os.path.expanduser('~'), '.vsf', 'ollama_last_restart')

PROBE_OK = 'ok'
PROBE_SERVICE_FAIL = 'service_fail'
PROBE_TRANSPORT_FAIL = 'transport_fail'


def _probe(max_time: int = 10) -> str:
    """Probe ollama via /api/tags (fast metadata endpoint — no model inference).
    Returns PROBE_OK / PROBE_SERVICE_FAIL / PROBE_TRANSPORT_FAIL.
    Uses /api/tags instead of /api/generate to avoid the 30-60s CPU-inference wait."""
    req = urllib.request.Request(f'{OLLAMA_URL}/api/tags', method='GET')
    try:
        with urllib.request.urlopen(req, timeout=max_time) as resp:
            data = resp.read()
            if data and MODEL.encode() in data:
                return PROBE_OK
            return PROBE_SERVICE_FAIL
    except urllib.error.URLError:
        return PROBE_TRANSPORT_FAIL
    except Exception:
        return PROBE_SERVICE_FAIL


def _restart_allowed() -> bool:
    try:
        with open(RESTART_STAMP, encoding='utf-8') as f:
            last = float(f.read().strip())
    except (OSError, ValueError):
        return True
    return (time.time() - last) >= RESTART_COOLDOWN_S


def _record_restart() -> None:
    os.makedirs(os.path.dirname(RESTART_STAMP), exist_ok=True)
    with open(RESTART_STAMP, 'w', encoding='utf-8') as f:
        f.write(str(time.time()))


def _try_restart_ssh(source: str, alerts_dir: str) -> bool:
    """Attempt ollama restart via SSH to n02 host (LXC 107 → n02 → pct exec 101).
    Returns True if restart succeeded; self-alerts and returns False if SSH path
    is unavailable (expected when LXC 107 has no SSH key to n02)."""
    try:
        r = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@n02',
             'pct exec 101 -- flock -w 300 /var/lib/vsf/qwen.lock systemctl restart ollama'],
            capture_output=True, timeout=330,
        )
        return r.returncode == 0
    except Exception as e:
        self_alert('Ollama restart — SSH path unavailable from LXC 107',
                   f'SSH to root@n02 failed: {e}',
                   'restart manually: ssh n02 && pct exec 101 -- systemctl restart ollama',
                   alerts_dir, source)
        return False


def ensure_ollama(alerts_dir: str = ALERTS_DIR, source: str = 'qwen_client') -> bool:
    """Health-check /api/tags on LXC 101. Restart only on confirmed service
    failure, at most once per cooldown window. Returns True if Qwen is ready."""
    state = _probe()
    if state == PROBE_OK:
        return True

    if state == PROBE_TRANSPORT_FAIL:
        self_alert('Qwen transport failure',
                   f'direct HTTP probe to {OLLAMA_URL} failed — network or firewall issue',
                   'check vsf_llm llm_allow on LXC 101; verify ollama is running',
                   alerts_dir, source)
        return False

    # Confirmed service failure — attempt restart
    if not _restart_allowed():
        self_alert('Ollama down — restart suppressed by cooldown',
                   f'GENERATE_FAIL confirmed but last restart < {RESTART_COOLDOWN_S}s ago',
                   'human/S3 intervention required — restart storm guard active',
                   alerts_dir, source)
        return False

    print(f'{source}: Ollama unresponsive — attempting restart via n02 SSH ...',
          file=sys.stderr)
    _record_restart()
    if not _try_restart_ssh(source, alerts_dir):
        return False

    print(f'{source}: waiting 20s for Ollama to initialise ...', file=sys.stderr)
    time.sleep(20)
    for attempt in range(8):
        if _probe(max_time=60) == PROBE_OK:
            print(f'{source}: Ollama ready (attempt {attempt + 1}).', file=sys.stderr)
            return True
        time.sleep(10)

    self_alert('Ollama failed to recover after restart',
               '8 HTTP probes failed post-restart',
               'human/S3 intervention required on LXC 101',
               alerts_dir, source)
    return False


def generate(function: str, prompt: str, num_predict: int = 300,
             temperature: float = 0.2, max_time: int = 420,
             num_ctx: int = 8192,
             alerts_dir: str = ALERTS_DIR):
    """Direct HTTP generate. Returns response text; '' = empty, None = failure
    (already self-alerted). Streams NDJSON and parses incrementally.
    num_ctx: context window tokens. Qwen2.5-coder 7B supports up to 32K;
    default 8192 (2× the ollama default) gives SA auditor headroom for large prompts."""
    if not ensure_ollama(alerts_dir, source=function):
        return None

    payload = json.dumps({
        'model': MODEL,
        'stream': True,
        'options': {'num_predict': num_predict, 'temperature': temperature,
                    'num_ctx': num_ctx},
        'prompt': prompt,
    }).encode()
    req = urllib.request.Request(
        f'{OLLAMA_URL}/api/generate', data=payload,
        headers={'Content-Type': 'application/json'}, method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=max_time) as resp:
            parts = []
            for raw in resp:
                line = raw.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if d.get('response'):
                        parts.append(d['response'])
                    if d.get('done'):
                        break
                except json.JSONDecodeError:
                    pass
            text = ''.join(parts).strip()
    except urllib.error.URLError as e:
        self_alert('Qwen transport failure mid-call',
                   f'HTTP generate failed: {e}',
                   'check ollama on LXC 101; NOT restarted',
                   alerts_dir, function)
        return None
    except Exception as e:
        self_alert('Qwen generate error',
                   f'unexpected error during HTTP generate: {e}',
                   'check LXC 107 → LXC 101 connectivity (10.10.20.10:11434)',
                   alerts_dir, function)
        return None

    if not text:
        self_alert('Empty Qwen response',
                   'HTTP transport OK but generate returned no text',
                   'check ollama model availability on LXC 101',
                   alerts_dir, function)
    return text
