#!/usr/bin/env python3
"""
CH.d — CHECO what-if narrator orchestrator.
Qwen translates a NL scenario → perturbation spec → KernelStepper engine → Qwen narrates.

R10: the deterministic engine (vsf-nucleus --experiment checo_whatif) is NEVER replaced by LLM.
     Qwen only translates intent and narrates the deterministic result.

Usage (from LXC 101 or via SSH):
    python3 checo_whatif_narrator.py "<scenario>"
    python3 checo_whatif_narrator.py "¿qué pasa si el sistema pierde toda su capacidad cómputo?"

Environment variables:
    QWEN_URL       Ollama base URL (default: http://localhost:11434)
    QWEN_MODEL     Ollama model name (default: qwen2.5-coder:7b)
    NUCLEUS_BIN    Path to vsf-nucleus binary (default: /root/vsf-nucleus/target/release/vsf-nucleus)
    NUCLEUS_SSH    If set, run binary via "ssh <NUCLEUS_SSH> <NUCLEUS_BIN> ..." (e.g. "root@n02 pct exec 108 --")
"""

import json, os, re, subprocess, sys, textwrap
import urllib.request, urllib.error

# CH.e: import env snapshot if available alongside this script
def _try_import_env_snapshot():
    try:
        sys.path.insert(0, os.path.dirname(__file__) or "/tmp")
        from checo_env_snapshot import snapshot, brief
        return snapshot, brief
    except ImportError:
        return None, None

QWEN_URL    = os.environ.get("QWEN_URL",    "http://localhost:11434")
QWEN_MODEL  = os.environ.get("QWEN_MODEL",  "qwen2.5-coder:7b")
NUCLEUS_BIN = os.environ.get("NUCLEUS_BIN", "/root/vsf-nucleus/target/release/vsf-nucleus")
NUCLEUS_SSH = os.environ.get("NUCLEUS_SSH", "")  # e.g. "root@n02 pct exec 108 --" for dev

# ── System prompts ─────────────────────────────────────────────────────────────

STEP1_SYSTEM = textwrap.dedent("""
    You are the CHECO S4 analyst for a Viable System Framework kernel.
    Your task: given a stress scenario, output a JSON perturbation specification.

    Available perturbation types:
    - "occupation": direct occupation state entropy injection. s=0=no change, s=1=maximum entropy.
      Use for: entropy spikes, informational chaos, state corruption.
    - "w4b": sustained thermal/load pressure via the W4b channel (kT_eff). s=0=idle, s=1=max load.
      Use for: CPU saturation, thermal stress, sustained high load.

    Calibration (measured 2026-06-20):
    - occupation s=1.0: excursion_envelope=0.9972, recovery=53 ticks, viable throughout
    - w4b s=1.0:        excursion_envelope=0.9990, recovery ~200 ticks, viable throughout
    - real hardware thermal: 0.9377 (not modelable offline — mechanism-specific)
    - ALL perturbations: system ALWAYS recovers (globally contracting attractor, λ_max=ln(0.99)<0)

    Respond ONLY with valid JSON on a single line:
    {"type": "occupation" or "w4b", "magnitude": 0.0-1.0, "rationale": "one sentence"}
""").strip()

STEP2_SYSTEM = textwrap.dedent("""
    You are the CHECO S4 narrator for a Viable System Framework kernel.
    Given a what-if simulation result, write a 2-3 sentence narrative.

    Be specific: mention the excursion depth (min_cos_fixed), recovery time in ticks,
    and whether the system stayed viable throughout. If the gap to the real-hardware thermal
    envelope (0.9377) is relevant, mention it honestly. The system ALWAYS recovers — never
    suggest collapse is possible (the attractor is globally contracting).
    Respond in the same language as the original scenario.
""").strip()


# ── Qwen interface ─────────────────────────────────────────────────────────────

def call_qwen(system_prompt: str, user_prompt: str) -> str:
    prompt = (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )
    payload = json.dumps({
        "model": QWEN_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 512},
    }).encode()
    req = urllib.request.Request(
        f"{QWEN_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            return json.loads(resp.read())["response"].strip()
    except urllib.error.URLError as e:
        raise RuntimeError(f"Qwen unreachable at {QWEN_URL}: {e}") from e


def parse_spec(raw: str) -> dict:
    """Extract JSON spec from Qwen response (handles extra text around the JSON)."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"type": "occupation", "magnitude": 1.0, "rationale": "parse_fallback"}


# ── Binary interface ───────────────────────────────────────────────────────────

def run_nucleus(ptype: str, magnitude: float) -> dict:
    """Run vsf-nucleus --experiment checo_whatif and return parsed JSON result."""
    nucleus_args = f"--experiment checo_whatif --type {ptype} --delta {magnitude:.3f}"
    if NUCLEUS_SSH:
        cmd = f"ssh {NUCLEUS_SSH} {NUCLEUS_BIN} {nucleus_args} 2>/dev/null"
    else:
        cmd = f"{NUCLEUS_BIN} {nucleus_args} 2>/dev/null"
    result = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=120)
    # Extract the JSON block from stdout (skip header/footer lines)
    lines = result.stdout.splitlines()
    in_json, depth, json_lines = False, 0, []
    for line in lines:
        if not in_json and line.strip().startswith("{"):
            in_json = True
        if in_json:
            json_lines.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                break
    if not json_lines:
        raise RuntimeError(f"No JSON in binary output.\nstdout={result.stdout}\nstderr={result.stderr}")
    return json.loads("\n".join(json_lines))


# ── Orchestrator ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    scenario = " ".join(sys.argv[1:])
    print(f"\n⟦ CH.d CHECO narrator | vsm-1.0 ⟧")
    print(f"scenario: {scenario}\n")

    # Step 1: NL → perturbation spec (Qwen)
    print("→ [1/3] translating scenario → perturbation spec (Qwen)...")
    raw_spec = call_qwen(STEP1_SYSTEM, scenario)
    spec = parse_spec(raw_spec)
    ptype     = spec.get("type", "occupation")
    magnitude = float(spec.get("magnitude", 1.0))
    rationale = spec.get("rationale", "")
    print(f"         type={ptype}  magnitude={magnitude:.2f}")
    print(f"         rationale: {rationale}")

    # CH.e: capture real environment snapshot before running engine
    env_snapshot, env_brief_fn = _try_import_env_snapshot()
    env = None
    if env_snapshot:
        try:
            env = env_snapshot()
            print(f"→ [CH.e] env: {env_brief_fn(env)}")
        except Exception as e:
            print(f"→ [CH.e] env snapshot failed: {e}")

    # Step 2: deterministic engine (KernelStepper) — R10: no LLM here
    print("→ [2/3] running KernelStepper engine (deterministic, R10)...")
    engine_result = run_nucleus(ptype, magnitude)
    res = engine_result.get("result", {})
    vrd = engine_result.get("verdict", {})
    print(f"         min_cos_fixed={res.get('min_cos_fixed', '?'):.4f}  "
          f"viable={res.get('always_viable')}  "
          f"recovery={res.get('recovery_ticks')} ticks")
    print(f"         gap_to_hardware={vrd.get('gap_to_hardware_thermal', '?'):+.4f}")

    # Step 3: narration (Qwen)
    print("→ [3/3] generating narrative (Qwen)...")
    env_context = ""
    if env:
        env_context = (
            f"\nCurrent system environment (CH.e real snapshot):\n"
            f"  env_class={env['env_class']}  "
            f"cpu_psi_avg10={env['pressure']['cpu_psi_avg10']:.2f}%  "
            f"w4b_magnitude={env['pressure']['w4b_magnitude']:.4f}  "
            f"thermal={env['thermal']['primary_c']}°C (normalized={env['thermal']['normalized']:.3f})  "
            f"stasis={env['telemetry']['stasis_last']}  "
            f"trust={env['telemetry']['trust1_last']}  "
            f"synthetic_load={env['telemetry']['synthetic_load']}\n"
            f"  hardware_thermal_ref=0.9377 (EXP-CA-01 Alt D)\n"
        )

    narration_prompt = (
        f"Scenario: {scenario}\n\n"
        f"Perturbation applied: {ptype}, magnitude={magnitude:.2f}\n"
        f"Rationale: {rationale}\n"
        f"{env_context}\n"
        f"Engine result:\n{json.dumps(engine_result, indent=2, ensure_ascii=False)}"
    )
    narration = call_qwen(STEP2_SYSTEM, narration_prompt)

    print(f"\n── CHECO Narrative {'─' * 42}")
    print(narration)
    print(f"{'─' * 56}")
    print(f"\n⟦ /CH.d | R10 compliant | vsm-1.0 ⟧")

    return {
        "scenario": scenario,
        "spec": spec,
        "engine_result": engine_result,
        "narration": narration,
    }


if __name__ == "__main__":
    main()
