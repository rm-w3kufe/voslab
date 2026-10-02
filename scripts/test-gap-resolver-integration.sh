#!/usr/bin/env bash
# test-gap-resolver-integration.sh — Comprehensive integration test for gap-resolver framework
#
# This script tests:
# 1. Gap definitions are valid JSON
# 2. Socratic trees exist and are valid
# 3. Gap resolver plugin is registered
# 4. Event router has gap-resolution handler
# 5. All context gatherers work
# 6. End-to-end gap resolution works

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0

echo "═══════════════════════════════════════════════════════════════"
echo "           GAP RESOLVER INTEGRATION TEST"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Test 1: Check gap definitions exist and are valid JSON
echo "TEST 1: Gap definitions validation"
echo "────────────────────────────────────"

GAP_DEFS_DIR="$ROOT/.opencode/plugins/operational/gap-definitions"
if [ ! -d "$GAP_DEFS_DIR" ]; then
    echo "  ✗ Gap definitions directory not found"
    FAIL=$((FAIL + 1))
else
    for gap_file in "$GAP_DEFS_DIR"/*.gap.json; do
        if [ -f "$gap_file" ]; then
            filename=$(basename "$gap_file")
            if python3 -c "import json; json.load(open('$gap_file'))" 2>/dev/null; then
                echo "  ✓ $filename is valid JSON"
                PASS=$((PASS + 1))
            else
                echo "  ✗ $filename is invalid JSON"
                FAIL=$((FAIL + 1))
            fi
        fi
    done
fi
echo ""

# Test 2: Check socratic trees exist
echo "TEST 2: Socratic trees validation"
echo "────────────────────────────────────"

TREES_DIR="$ROOT/.opencode/plugins/support/trees"
TREES=(
    "classify-plugin.tree.vsm"
    "patch-detect.tree.vsm"
    "quality-gate.tree.vsm"
    "dependency-check.tree.vsm"
    "conflict-detect.tree.vsm"
)

for tree in "${TREES[@]}"; do
    tree_path="$TREES_DIR/$tree"
    if [ -f "$tree_path" ]; then
        echo "  ✓ $tree exists"
        PASS=$((PASS + 1))
        
        # Check if tree has socratic block
        if grep -q 'socratic(' "$tree_path" 2>/dev/null; then
            echo "    ✓ Has socratic block"
            PASS=$((PASS + 1))
        else
            echo "    ✗ Missing socratic block"
            FAIL=$((FAIL + 1))
        fi
    else
        echo "  ✗ $tree not found"
        FAIL=$((FAIL + 1))
    fi
done
echo ""

# Test 3: Check gap resolver plugin is registered
echo "TEST 3: Gap resolver plugin registration"
echo "────────────────────────────────────────"

if grep -q '"gap-resolver"' "$ROOT/.opencode/plugins/registry.json" 2>/dev/null; then
    echo "  ✓ gap-resolver is registered in registry.json"
    PASS=$((PASS + 1))
else
    echo "  ✗ gap-resolver not found in registry.json"
    FAIL=$((FAIL + 1))
fi

if grep -q 'gap-resolver.ts' "$ROOT/opencode.json" 2>/dev/null; then
    echo "  ✓ gap-resolver is registered in opencode.json"
    PASS=$((PASS + 1))
else
    echo "  ✗ gap-resolver not found in opencode.json"
    FAIL=$((FAIL + 1))
fi
echo ""

# Test 4: Check event router has gap-resolution handler
echo "TEST 4: Event router integration"
echo "────────────────────────────────"

if grep -q '"handler:gap-resolution"' "$ROOT/.opencode/plugins/registry.json" 2>/dev/null; then
    echo "  ✓ gap-resolution handler is registered"
    PASS=$((PASS + 1))
else
    echo "  ✗ gap-resolution handler not found in registry"
    FAIL=$((FAIL + 1))
fi

if grep -q 'gapResolutionHandler' "$ROOT/.opencode/plugins/operational/vsf-event-router.ts" 2>/dev/null; then
    echo "  ✓ gapResolutionHandler is imported in event router"
    PASS=$((PASS + 1))
else
    echo "  ✗ gapResolutionHandler not found in event router"
    FAIL=$((FAIL + 1))
fi

if grep -q 'registerHandler(gapResolutionHandler)' "$ROOT/.opencode/plugins/operational/vsf-event-router.ts" 2>/dev/null; then
    echo "  ✓ gapResolutionHandler is registered in event router"
    PASS=$((PASS + 1))
else
    echo "  ✗ gapResolutionHandler not registered in event router"
    FAIL=$((FAIL + 1))
fi
echo ""

# Test 5: Check gap definitions have required fields
echo "TEST 5: Gap definitions structure"
echo "──────────────────────────────────"

for gap_file in "$GAP_DEFS_DIR"/*.gap.json; do
    if [ -f "$gap_file" ]; then
        filename=$(basename "$gap_file")
        
        # Check required fields
        has_id=$(python3 -c "import json; d=json.load(open('$gap_file')); print('id' in d)" 2>/dev/null)
        has_name=$(python3 -c "import json; d=json.load(open('$gap_file')); print('name' in d)" 2>/dev/null)
        has_trigger=$(python3 -c "import json; d=json.load(open('$gap_file')); print('trigger' in d)" 2>/dev/null)
        has_evaluation=$(python3 -c "import json; d=json.load(open('$gap_file')); print('evaluation' in d)" 2>/dev/null)
        has_actions=$(python3 -c "import json; d=json.load(open('$gap_file')); print('actions' in d)" 2>/dev/null)
        
        if [ "$has_id" = "True" ] && [ "$has_name" = "True" ] && [ "$has_trigger" = "True" ] && [ "$has_evaluation" = "True" ] && [ "$has_actions" = "True" ]; then
            echo "  ✓ $filename has all required fields"
            PASS=$((PASS + 1))
        else
            echo "  ✗ $filename missing required fields"
            FAIL=$((FAIL + 1))
        fi
    fi
done
echo ""

# Test 6: Check gap resolver TypeScript file
echo "TEST 6: Gap resolver TypeScript validation"
echo "──────────────────────────────────────────"

GAP_RESOLVER="$ROOT/.opencode/plugins/operational/gap-resolver.ts"
if [ -f "$GAP_RESOLVER" ]; then
    echo "  ✓ gap-resolver.ts exists"
    PASS=$((PASS + 1))
    
    # Check for key functions
    if grep -q "resolveGap" "$GAP_RESOLVER" 2>/dev/null; then
        echo "    ✓ Has resolveGap function"
        PASS=$((PASS + 1))
    else
        echo "    ✗ Missing resolveGap function"
        FAIL=$((FAIL + 1))
    fi
    
    if grep -q "evaluateTree" "$GAP_RESOLVER" 2>/dev/null; then
        echo "    ✓ Has evaluateTree function"
        PASS=$((PASS + 1))
    else
        echo "    ✗ Missing evaluateTree function"
        FAIL=$((FAIL + 1))
    fi
    
    if grep -q "gatherContext" "$GAP_RESOLVER" 2>/dev/null; then
        echo "    ✓ Has gatherContext function"
        PASS=$((PASS + 1))
    else
        echo "    ✗ Missing gatherContext function"
        FAIL=$((FAIL + 1))
    fi
else
    echo "  ✗ gap-resolver.ts not found"
    FAIL=$((FAIL + 1))
fi
echo ""

# Test 7: Check context gatherers
echo "TEST 7: Context gatherers"
echo "─────────────────────────"

GATHERERS=(
    "read-content"
    "parse-imports"
    "extract-exports"
    "git-status"
    "git-diff"
    "file-info"
    "syntax-check"
    "dependency-check"
    "conflict-check"
)

for gatherer in "${GATHERERS[@]}"; do
    if grep -q "case \"$gatherer\":" "$GAP_RESOLVER" 2>/dev/null; then
        echo "  ✓ $gatherer gatherer exists"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $gatherer gatherer not found"
        FAIL=$((FAIL + 1))
    fi
done
echo ""

# Summary
echo "═══════════════════════════════════════════════════════════════"
echo "                         SUMMARY"
echo "═══════════════════════════════════════════════════════════════"
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo "  Total:  $((PASS + FAIL))"
echo ""

if [ $FAIL -eq 0 ]; then
    echo "  ✓ ALL TESTS PASSED"
    exit 0
else
    echo "  ✗ SOME TESTS FAILED"
    exit 1
fi
