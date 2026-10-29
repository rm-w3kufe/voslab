#!/usr/bin/env bash
# scenario_memory_dashboard.sh — Dashboard for Scenario Memory metrics.
#
# Shows: procedures, matching, adaptation, autonomy score, health.
#
# Usage:
#   bash scripts/state/monitoring/scenario_memory_dashboard.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

PROCEDURES_DIR="$ROOT/docs/learning_records/procedures"
RECORDS_DIR="$ROOT/docs/learning_records/learning-record"

echo "═══════════════════════════════════════════════════════════════════"
echo "Scenario Memory Dashboard"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Count procedures
if [ -d "$PROCEDURES_DIR" ]; then
    TOTAL=$(find "$PROCEDURES_DIR" -name "*.json" 2>/dev/null | wc -l)
    echo "📊 Procedures: $TOTAL"
else
    echo "📊 Procedures: 0 (directory not found)"
fi

# Count learning records
if [ -d "$RECORDS_DIR" ]; then
    RECORDS=$(find "$RECORDS_DIR" -name "*.vsm" 2>/dev/null | wc -l)
    echo "📚 Learning Records: $RECORDS"
else
    echo "📚 Learning Records: 0 (directory not found)"
fi

echo ""

# Run stats if procedures exist
if [ "$TOTAL" -gt 0 ]; then
    echo "═══ PROCEDURE METRICS ═══"
    python3 "$ROOT/scripts/state/monitoring/learning_stats.py" --procedures 2>/dev/null || echo "  (metrics unavailable)"
    echo ""
fi

# Check for recent activity
echo "═══ RECENT ACTIVITY ═══"
if [ -d "$PROCEDURES_DIR" ]; then
    RECENT=$(find "$PROCEDURES_DIR" -name "*.json" -mtime -7 2>/dev/null | wc -l)
    echo "  Last 7 days: $RECENT procedures"
else
    echo "  No recent procedures"
fi

echo ""

# Health check
echo "═══ HEALTH ═══"
ERRORS=0

# Check if procedures directory exists
if [ ! -d "$PROCEDURES_DIR" ]; then
    echo "  ⚠ Procedures directory not found"
    ERRORS=$((ERRORS + 1))
fi

# Check if learning records directory exists
if [ ! -d "$RECORDS_DIR" ]; then
    echo "  ⚠ Learning records directory not found"
    ERRORS=$((ERRORS + 1))
fi

# Check if stats script exists
if [ ! -f "$ROOT/scripts/state/monitoring/learning_stats.py" ]; then
    echo "  ⚠ learning_stats.py not found"
    ERRORS=$((ERRORS + 1))
fi

if [ "$ERRORS" -eq 0 ]; then
    echo "  ✓ All systems operational"
else
    echo "  ⚠ $ERRORS issues detected"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════"
