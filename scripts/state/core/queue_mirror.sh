#!/bin/bash
# queue_mirror.sh — TELEMETRY-01 rewire (S5 "todo aprobado" 2026-10-09).
# Mirror del ledger_A vivo (LXC104) → fila única queue_state en el state.db
# del host n02. LXC101 (nucleus) lo ve vía mp0 read-only bind mount del
# host (pct config: mp0=/var/lib/vsf-state,ro=1) — lectura del feeder,
# escritura del mirror SOLO host-side.
#
# Por qué: el feeder leía algedonic_ledger = ledger_B RETIRADA (1456 filas
# congeladas desde jul-26 → queue_up=1.0 pinneado, absorption=0.0 — clase-S
# declarada en P4). Con este timer el feeder siente la cola REAL de NATS.
#
# feeder_stale: el feeder valida mirrored_at con max_age 900s (canon P4
# state/telemetry_ports.json). Cadencia 5min → 3 ciclos fallidos antes de
# stale. Lock-safe: .timeout 10000 en ambos sqlite (clase del incidente
# Oct-7 write-lock; state.db es vivo con writers concurrentes).
set -euo pipefail

TARGET_DB="/var/lib/vsf-state/state.db"

# 1. ledger_A vía pct exec (timeout anti-busy, mismo fix que vsf-q)
ROW=$(pct exec 104 -- sqlite3 -cmd ".timeout 10000" /root/algedonic/ledger.db \
  "SELECT COUNT(*) FILTER (WHERE status='pending_human') \
        || '|' || COUNT(*) \
        || '|' || COUNT(*) FILTER (WHERE status IN ('auto_handled','acked')) \
        || '|' || COALESCE(MAX(ts),'') \
   FROM algedonic_ledger")

IFS='|' read -r PENDING TOTAL HANDLED NEWEST_TS <<< "$ROW"
NOW=$(date -u +%s)

# 2. upsert host-side en queue_state (101 lo lee vía bind ro — mismo inode)
sqlite3 -cmd ".timeout 10000" "$TARGET_DB" \
  "CREATE TABLE IF NOT EXISTS queue_state (
     id           INTEGER PRIMARY KEY CHECK (id = 1),
     pending      INTEGER NOT NULL,
     total        INTEGER NOT NULL,
     handled      INTEGER NOT NULL,
     mirrored_at  INTEGER NOT NULL,
     source_ledger TEXT   NOT NULL
   );
   INSERT INTO queue_state (id,pending,total,handled,mirrored_at,source_ledger)
   VALUES (1,$PENDING,$TOTAL,$HANDLED,$NOW,'ledger_A:104:/root/algedonic/ledger.db')
   ON CONFLICT(id) DO UPDATE SET
     pending=$PENDING, total=$TOTAL, handled=$HANDLED,
     mirrored_at=$NOW, source_ledger='ledger_A:104:/root/algedonic/ledger.db';"

echo "queue_mirror: pending=$PENDING total=$TOTAL handled=$HANDLED newest=$NEWEST_TS mirrored_at=$NOW -> $TARGET_DB queue_state"
