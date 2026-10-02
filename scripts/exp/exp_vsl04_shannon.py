#!/usr/bin/env python3
"""
EXP-VSL-04: Shannon H(VSL) vs H(NL) — grammar as codebook efficiency.

Character-level Shannon entropy of VSL instructions vs equivalent natural language
prompts. If H(VSL) < H(NL) for the same semantic content, grammar IS a codebook
(a lower-entropy encoding = a more constrained symbol space).

Run: python3 scripts/exp/exp_vsl04_shannon.py
"""

import os
import math
from collections import Counter

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

BASE = os.path.join(os.path.dirname(__file__), "..", "docs", "experiments", "vsl_compression")

NL_FILES = {
    "pvsnp":              "prompt_A.txt",
    "thermal_senescence": "prompt_A2.txt",
    "spec_boot_lyapunov": "prompt_A3.txt",
    "proxmox_s4":         "prompt_A4.txt",
    "psi_1_0":            "prompt_A5.txt",
}

VSL_FILES = {
    "pvsnp":              ["instruccion_B.vsm"],
    "thermal_senescence": ["instruccion_B2.vsm"],
    "spec_boot_lyapunov": ["instruccion_B3a.vsm", "instruccion_B3b.vsm"],
    "proxmox_s4":         ["instruccion_B4a.vsm", "instruccion_B4b.vsm"],
    "psi_1_0":            ["instruccion_B5a.vsm", "instruccion_B5b.vsm"],
}

VSL_LABEL = {
    "pvsnp":              "B",
    "thermal_senescence": "B2",
    "spec_boot_lyapunov": "B3a (full) / B3b (schema)",
    "proxmox_s4":         "B4a (full) / B4b (schema)",
    "psi_1_0":            "B5a (full) / B5b (schema)",
}


def shannon_entropy(text: str) -> float:
    """Character-level Shannon entropy in bits."""
    counts = Counter(text)
    total = len(text)
    if total == 0:
        return 0.0
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def token_entropy(text: str, enc_name: str = "cl100k_base") -> float | None:
    """Token-level Shannon entropy using tiktoken."""
    if not HAS_TIKTOKEN:
        return None
    enc = tiktoken.get_encoding(enc_name)
    tokens = enc.encode(text)
    counts = Counter(tokens)
    total = len(tokens)
    if total == 0:
        return 0.0
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def read_file(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


def print_row(case: str, label: str, chars: int, entropy: float,
              entropy_per_byte: float, unique_chars: int):
    print(f"  {case:22s} {label:22s} {chars:6d} {entropy:8.4f}  "
          f"{entropy_per_byte:8.4f}  {unique_chars:4d}")


def main():
    print("=" * 80)
    print("EXP-VSL-04: Shannon entropy of VSL vs Natural Language")
    print("=" * 80)
    print()
    print(f"{'Case':22s} {'File':22s} {'Chars':>6s} {'H_char':>8s}  "
          f"{'H/byte':>8s}  {'Uniq':>4s}")
    print("-" * 80)

    results_nl = {}
    results_vsl = {}
    results_vsl_schema = {}

    for case in sorted(NL_FILES):
        nl_path = os.path.join(BASE, NL_FILES[case])
        nl_text = read_file(nl_path)
        h_nl = shannon_entropy(nl_text)
        results_nl[case] = {
            "chars": len(nl_text),
            "entropy": h_nl,
            "entropy_per_byte": h_nl / len(nl_text) if len(nl_text) > 0 else 0,
            "unique": len(set(nl_text)),
        }
        print_row(case, NL_FILES[case], results_nl[case]["chars"],
                  results_nl[case]["entropy"],
                  results_nl[case]["entropy_per_byte"],
                  results_nl[case]["unique"])

        vsl_files = VSL_FILES[case]
        # Full VSL = all files concatenated (full + schema when both exist)
        vsl_full_text = ""
        vsl_schema_text = None
        for fname in vsl_files:
            vsl_path = os.path.join(BASE, fname)
            vsl_text = read_file(vsl_path)
            vsl_full_text += vsl_text
            # B*b files = schema-only
            if fname.endswith("b.vsm"):
                vsl_schema_text = vsl_text

        h_vsl = shannon_entropy(vsl_full_text)
        label = VSL_LABEL[case]
        results_vsl[case] = {
            "files": VSL_FILES[case],
            "chars": len(vsl_full_text),
            "entropy": h_vsl,
            "entropy_per_byte": h_vsl / len(vsl_full_text) if len(vsl_full_text) > 0 else 0,
            "unique": len(set(vsl_full_text)),
        }
        print_row(case, label, results_vsl[case]["chars"],
                  results_vsl[case]["entropy"],
                  results_vsl[case]["entropy_per_byte"],
                  results_vsl[case]["unique"])

        # Schema-only measure (when available)
        if vsl_schema_text is not None:
            h_schema = shannon_entropy(vsl_schema_text)
            results_vsl_schema[case] = {
                "chars": len(vsl_schema_text),
                "entropy": h_schema,
                "entropy_per_byte": h_schema / len(vsl_schema_text) if len(vsl_schema_text) > 0 else 0,
                "unique": len(set(vsl_schema_text)),
            }
            print_row(case, "  (B*b schema-only)", results_vsl_schema[case]["chars"],
                      results_vsl_schema[case]["entropy"],
                      results_vsl_schema[case]["entropy_per_byte"],
                      results_vsl_schema[case]["unique"])
        print()

    # Summary
    print()
    print("=" * 80)
    print("SUMMARY: H(VSL) vs H(NL) comparison")
    print("=" * 80)
    print(f"\n{'Case':22s} {'H(NL)':>8s} {'H(VSL)':>8s} {'Δ':>8s} "
          f"{'Δ%':>8s} {'H_closer':>12s}")
    print("-" * 80)

    total_h_nl = 0
    total_h_vsl = 0
    count = 0

    for case in sorted(results_nl):
        hn = results_nl[case]["entropy"]
        hs = results_vsl[case]["entropy"]
        delta = hs - hn
        delta_pct = ((hs - hn) / hn) * 100 if hn > 0 else 0
        closer = "NL" if delta > 0 else "VSL"
        print(f"  {case:22s} {hn:8.4f} {hs:8.4f} {delta:+8.4f} {delta_pct:+7.2f}% "
              f"{closer:>12s}")
        total_h_nl += hn
        total_h_vsl += hs
        count += 1

    print()
    avg_nl = total_h_nl / count
    avg_vsl = total_h_vsl / count
    avg_delta = avg_vsl - avg_nl
    avg_pct = ((avg_vsl - avg_nl) / avg_nl) * 100
    print(f"  {'AVERAGE':22s} {avg_nl:8.4f} {avg_vsl:8.4f} {avg_delta:+8.4f} "
          f"{avg_pct:+7.2f}%")

    # Per-byte comparison
    print()
    print("-" * 80)
    print("Per-byte entropy (H/byte):")
    print(f"{'Case':22s} {'NL H/byte':>10s} {'VSL H/byte':>10s}")
    print("-" * 80)
    for case in sorted(results_nl):
        hn_b = results_nl[case]["entropy_per_byte"]
        hs_b = results_vsl[case]["entropy_per_byte"]
        print(f"  {case:22s} {hn_b:10.6f} {hs_b:10.6f}")

    # Schema-only summary
    if results_vsl_schema:
        print()
        print("-" * 80)
        print("Schema-mode comparison (B*b only):")
        print(f"{'Case':22s} {'H(NL)':>8s} {'H(schema)':>8s} {'Δ':>8s}")
        print("-" * 80)
        for case in sorted(results_vsl_schema):
            hn = results_nl[case]["entropy"]
            hs = results_vsl_schema[case]["entropy"]
            delta = hs - hn
            print(f"  {case:22s} {hn:8.4f} {hs:8.4f} {delta:+8.4f}")

    # Token-level entropy (when tiktoken available)
    if HAS_TIKTOKEN:
        print()
        print("-" * 80)
        print("Token-level entropy (tiktoken cl100k_base):")
        print(f"{'Case':22s} {'H_tok(NL)':>10s} {'H_tok(VSL)':>10s} {'Δ':>10s}")
        print("-" * 80)

        total_ht_nl = 0
        total_ht_vsl = 0
        count_tok = 0

        for case in sorted(results_nl):
            nl_path = os.path.join(BASE, NL_FILES[case])
            nl_text = read_file(nl_path)
            ht_nl = token_entropy(nl_text)
            vsl_text = "".join(read_file(os.path.join(BASE, f)) for f in VSL_FILES[case])
            ht_vsl = token_entropy(vsl_text)
            if ht_nl is not None and ht_vsl is not None:
                delta = ht_vsl - ht_nl
                print(f"  {case:22s} {ht_nl:10.4f} {ht_vsl:10.4f} {delta:+10.4f}")
                total_ht_nl += ht_nl
                total_ht_vsl += ht_vsl
                count_tok += 1

        if count_tok > 0:
            avg_ht_nl = total_ht_nl / count_tok
            avg_ht_vsl = total_ht_vsl / count_tok
            avg_delta_tok = avg_ht_vsl - avg_ht_nl
            print(f"  {'AVERAGE':22s} {avg_ht_nl:10.4f} {avg_ht_vsl:10.4f} {avg_delta_tok:+10.4f}")

    print()
    print("=" * 80)
    print("CONCLUSION:")
    if avg_delta < 0:
        print("  CHAR LEVEL: H(VSL) < H(NL) — VSL is a lower-entropy encoding = codebook confirmed.")
    else:
        print("  CHAR LEVEL: H(VSL) > H(NL) — VSL uses a richer character set (punctuation, notation).")
        print("  This REFUTES naive 'grammar as codebook' at the character level, but is expected:")
        print("  VSL's compression lives at the token/semantic level (72-79% per EXP-BB-01).")
    print(f"  Mean H_char(NL) = {avg_nl:.4f} bits, Mean H_char(VSL) = {avg_vsl:.4f} bits")
    print("=" * 80)


if __name__ == "__main__":
    main()
