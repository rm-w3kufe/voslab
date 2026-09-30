#!/usr/bin/env bash
# scenario_memory_monitor.sh — Monitor Scenario Memory metrics over time.
#
# Creates snapshots and tracks changes in autonomy score, procedures, etc.
#
# Usage:
#   bash scripts/state/monitoring/scenario_memory_monitor.sh [snapshot|diff|status]

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
METRICS_DIR="$ROOT/docs/spec_revision/learning_records/metrics"
PROCEDURES_DIR="$ROOT/docs/spec_revision/learning_records/procedures"
RECORDS_DIR="$ROOT/docs/spec_revision/learning_records/learning-record"

# Ensure metrics directory exists
mkdir -p "$METRICS_DIR"

# Get current timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SNAPSHOT_FILE="$METRICS_DIR/snapshot_${TIMESTAMP}.json"
LATEST_LINK="$METRICS_DIR/latest.json"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

show_status() {
    echo "═══════════════════════════════════════════════════════════════════"
    echo "Scenario Memory — Status"
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""
    
    # Procedures
    if [ -d "$PROCEDURES_DIR" ]; then
        TOTAL=$(find "$PROCEDURES_DIR" -name "*.json" 2>/dev/null | wc -l)
        echo -e "📊 Procedures: ${BLUE}$TOTAL${NC}"
    else
        echo -e "📊 Procedures: ${RED}0 (directory not found)${NC}"
    fi
    
    # Learning records
    if [ -d "$RECORDS_DIR" ]; then
        RECORDS=$(find "$RECORDS_DIR" -name "*.vsm" 2>/dev/null | wc -l)
        echo -e "📚 Learning Records: ${BLUE}$RECORDS${NC}"
    else
        echo -e "📚 Learning Records: ${RED}0 (directory not found)${NC}"
    fi
    
    # Metrics snapshots
    if [ -d "$METRICS_DIR" ]; then
        SNAPSHOTS=$(find "$METRICS_DIR" -name "snapshot_*.json" 2>/dev/null | wc -l)
        echo -e "📈 Metrics Snapshots: ${BLUE}$SNAPSHOTS${NC}"
    else
        echo -e "📈 Metrics Snapshots: ${RED}0${NC}"
    fi
    
    echo ""
    
    # Recent activity
    echo "═══ RECENT ACTIVITY ═══"
    if [ -d "$PROCEDURES_DIR" ]; then
        RECENT=$(find "$PROCEDURES_DIR" -name "*.json" -mtime -7 2>/dev/null | wc -l)
        echo "  Last 7 days: $RECENT procedures"
    else
        echo "  No recent procedures"
    fi
    
    echo ""
    
    # Health
    echo "═══ HEALTH ═══"
    ERRORS=0
    
    if [ ! -d "$PROCEDURES_DIR" ]; then
        echo -e "  ${YELLOW}⚠ Procedures directory not found${NC}"
        ERRORS=$((ERRORS + 1))
    fi
    
    if [ ! -d "$RECORDS_DIR" ]; then
        echo -e "  ${YELLOW}⚠ Learning records directory not found${NC}"
        ERRORS=$((ERRORS + 1))
    fi
    
    if [ ! -f "$ROOT/scripts/state/monitoring/learning_stats.py" ]; then
        echo -e "  ${YELLOW}⚠ learning_stats.py not found${NC}"
        ERRORS=$((ERRORS + 1))
    fi
    
    if [ "$ERRORS" -eq 0 ]; then
        echo -e "  ${GREEN}✓ All systems operational${NC}"
    else
        echo -e "  ${YELLOW}⚠ $ERRORS issues detected${NC}"
    fi
    
    echo ""
    echo "═══════════════════════════════════════════════════════════════════"
}

create_snapshot() {
    echo "═══════════════════════════════════════════════════════════════════"
    echo "Scenario Memory — Creating Snapshot"
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""
    
    # Get metrics
    METRICS=$(python3 "$ROOT/scripts/state/monitoring/learning_stats.py" --procedures --json 2>/dev/null || echo '{"error": "metrics unavailable"}')
    
    # Create snapshot
    SNAPSHOT=$(cat <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "metrics": $METRICS
}
EOF
)
    
    # Write snapshot
    echo "$SNAPSHOT" > "$SNAPSHOT_FILE"
    
    # Update latest link
    ln -sf "$SNAPSHOT_FILE" "$LATEST_LINK"
    
    echo -e "Snapshot created: ${GREEN}$SNAPSHOT_FILE${NC}"
    echo ""
    
    # Show snapshot
    echo "═══ SNAPSHOT CONTENTS ═══"
    echo "$SNAPSHOT" | python3 -m json.tool 2>/dev/null || echo "$SNAPSHOT"
    
    echo ""
    echo "═══════════════════════════════════════════════════════════════════"
}

show_diff() {
    echo "═══════════════════════════════════════════════════════════════════"
    echo "Scenario Memory — Metrics Diff"
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""
    
    if [ ! -d "$METRICS_DIR" ] || [ -z "$(ls -A "$METRICS_DIR"/snapshot_*.json 2>/dev/null)" ]; then
        echo "No snapshots found. Run '$0 snapshot' first."
        return 1
    fi
    
    # Get latest two snapshots
    LATEST=$(ls -t "$METRICS_DIR"/snapshot_*.json 2>/dev/null | head -1)
    PREVIOUS=$(ls -t "$METRICS_DIR"/snapshot_*.json 2>/dev/null | head -2 | tail -1)
    
    if [ "$LATEST" = "$PREVIOUS" ]; then
        echo "Only one snapshot exists. Run '$0 snapshot' again later to see changes."
        return 0
    fi
    
    echo "Previous: $PREVIOUS"
    echo "Latest:   $LATEST"
    echo ""
    
    # Compare metrics
    echo "═══ CHANGES ═══"
    # This is a simple diff - could be enhanced with jq
    diff <(python3 -m json.tool "$PREVIOUS" 2>/dev/null) <(python3 -m json.tool "$LATEST" 2>/dev/null) || true
    
    echo ""
    echo "═══════════════════════════════════════════════════════════════════"
}

# Main
case "${1:-status}" in
    status)
        show_status
        ;;
    snapshot)
        show_status
        echo ""
        create_snapshot
        ;;
    diff)
        show_diff
        ;;
    *)
        echo "Usage: $0 [status|snapshot|diff]"
        echo ""
        echo "Commands:"
        echo "  status    Show current status (default)"
        echo "  snapshot  Create metrics snapshot"
        echo "  diff      Show changes between snapshots"
        exit 1
        ;;
esac
