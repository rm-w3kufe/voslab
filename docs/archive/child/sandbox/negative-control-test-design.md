# negative-control-test design

Purpose: Verify that two gate false negatives are fixed.

## R18 false negative fix
- R18 now catches vsm-1.0 (too old to be valid legacy)
- Only versions within one minor version of canon are accepted as legacy
- vsm-1.2 still accepted as valid legacy

## Encoding check fix
- Encoding check now handles files outside repo (e.g., /tmp/)
- Uses try/except for relative_to() to avoid crash
- Reports emoji detection even for external files

## Verification
```bash
# Test R18 catches vsm-1.0
python3 scripts/vsl/validator/check.py /tmp/gate_test/test_bad_version.vsm

# Test encoding handles /tmp/
python3 scripts/vsl/validator/verify_encoding.py /tmp/gate_test/test_bad_encoding.vsm
```
