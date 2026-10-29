#!/usr/bin/env python3
# design: system/instance/vsf-instance-v1/instance.vsm (s5_ca_renewal)
# (R16_impl_with_design — S5-CRL-AUTORENEW-2026-08-16: helper del check
#  crl-expiry-proximity; lee next_update de s5_crl.json — SOLO lectura)
"""read_crl_next_update.py — read next_update from an s5_crl.json file.

Used by checks/crl-expiry-proximity (S5-CRL-AUTORENEW). Prints the
next_update value (ISO 8601) or nothing on error. Pure stdlib.
"""
import json
import sys


def main():
    if len(sys.argv) < 2:
        return 1
    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            crl = json.load(f)
        nu = crl.get("next_update", "")
        if nu:
            print(nu)
            return 0
    except (OSError, ValueError):
        pass
    return 1


if __name__ == "__main__":
    sys.exit(main())