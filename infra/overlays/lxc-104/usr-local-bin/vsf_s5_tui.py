#!/usr/bin/env python3
"""vsf-s5-tui — ITEM_16.4: S5 algedonic TUI.

Acceso: ssh n02 'lxc-attach -n 104 -- python3 /usr/local/bin/vsf_s5_tui.py'
        o directamente desde LXC 104: python3 /usr/local/bin/vsf_s5_tui.py

Sin puertos — interfaz de terminal pura.

Muestra TODO el algedonic_ledger con colores por status:
  [AUTO]    — manejado por autopiloto
  [PENDING] — esperando ACK humano   ← resaltado
  [ACKED]   — confirmado por humano
  [REJECT]  — rechazado por humano

Comandos disponibles desde la TUI:
  a <id>  — ACK (+ nota opcional)
  r <id>  — Reject
  q       — quit
"""
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

LEDGER_DB = os.environ.get("LEDGER_DB", "/root/algedonic/ledger.db")

# ── Color codes (ANSI, sin dependencias externas) ─────────────────────────────
RED     = "\033[91m"
YELLOW  = "\033[93m"
GREEN   = "\033[92m"
CYAN    = "\033[96m"
GREY    = "\033[90m"
BOLD    = "\033[1m"
RESET   = "\033[0m"
CLEAR   = "\033[2J\033[H"

STATUS_COLOR = {
    "pending_human": RED + BOLD,
    "agent_handled": CYAN,
    "auto_handled":  CYAN,
    "acked":         GREEN,
    "rejected":      GREY,
    "deferred":      YELLOW,
}
STATUS_LABEL = {
    "pending_human": "PENDING",
    "agent_handled": "AUTO   ",
    "auto_handled":  "AUTO   ",
    "acked":         "ACKED  ",
    "rejected":      "REJECT ",
    "deferred":      "DEFER  ",
}


def open_db() -> sqlite3.Connection:
    if not Path(LEDGER_DB).exists():
        print(f"Ledger DB not found: {LEDGER_DB}")
        print("Is vsf-s5-ledger running? Start it first.")
        sys.exit(1)
    db = sqlite3.connect(LEDGER_DB, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def render(db: sqlite3.Connection, filter_status: str = None, limit: int = 40) -> None:
    print(CLEAR, end="")
    print(f"{BOLD}VSF S5 Algedonic Ledger{RESET}  [{now_iso()}]")
    print(f"DB: {LEDGER_DB}")
    print()

    # Summary counts
    counts = dict(db.execute(
        "SELECT status, COUNT(*) FROM algedonic_ledger GROUP BY status"
    ).fetchall())
    pending = counts.get("pending_human", 0)
    total   = sum(counts.values())
    print(
        f"Total: {total}  |  "
        f"{RED}{BOLD}PENDING: {pending}{RESET}  |  "
        f"{YELLOW}DEFER: {counts.get('deferred', 0)}{RESET}  |  "
        f"{CYAN}AUTO: {counts.get('auto_handled', 0)}{RESET}  |  "
        f"{GREEN}ACKED: {counts.get('acked', 0)}{RESET}  |  "
        f"{GREY}REJECT: {counts.get('rejected', 0)}{RESET}"
    )
    print("─" * 80)

    # Header — ALG-DEDUP-PROCEDURE: show ×N after type
    print(f"{'ID':>5}  {'STATUS ':8}  {'SEV':>4}  {'TYPE':<18}  {'×CNT':>5}  {'SOURCE':<12}  {'TS':<24}  ACTION")
    print("─" * 80)

    where = f"WHERE status='{filter_status}'" if filter_status else ""
    rows = db.execute(
        f"SELECT * FROM algedonic_ledger {where} ORDER BY id DESC LIMIT {limit}"
    ).fetchall()

    if not rows:
        print(f"{GREY}  (no entries){RESET}")
    for row in rows:
        col   = STATUS_COLOR.get(row["status"], "")
        label = STATUS_LABEL.get(row["status"], row["status"][:7])
        sev   = row["severity"]
        sev_c = RED if sev >= 7 else YELLOW if sev >= 4 else GREEN
        action = (row["action_auto"] or row["action_human"] or "—")[:30]
        ts     = row["ts"][:19].replace("T", " ")
        dup    = row["dup_count"] or 1
        dup_s  = f"{dup:>3d}x" if dup > 1 else "     "
        # Check procedure status from agent_note
        note = row["agent_note"] or ""
        proc_status = ""
        if "PROCEDURE:" in note:
            done = note.count("✅")
            total = note.count("PROCEDURE:\n")
            # Count steps (numbered lines after PROCEDURE:)
            steps = len(re.findall(r'^\d+\.', note, re.MULTILINE))
            proc_status = f"{GREY}  step?/{steps}" if steps else ""
        print(
            f"{row['id']:>5}  {col}[{label}]{RESET}  "
            f"{sev_c}{sev:>4.1f}{RESET}  "
            f"{row['type']:<18}  {dup_s}  {row['source']:<12}  {ts}  {action}{proc_status}"
        )

    print("─" * 80)
    print(f"Commands: {BOLD}a <id>{RESET} ACK  {BOLD}r <id>{RESET} Reject  "
          f"{BOLD}d <id>{RESET} Defer  {BOLD}p <id>{RESET} Detail  "
          f"{BOLD}f pending{RESET} Filter  {BOLD}f all{RESET}  "
          f"{BOLD}h{RESET} Help  {BOLD}q{RESET} Quit")


def show_detail(db: sqlite3.Connection, entry_id: int) -> None:
    """Show rich detail for a ledger entry: parsed payload + history + rule info."""
    import json

    row = db.execute("SELECT * FROM algedonic_ledger WHERE id=?", (entry_id,)).fetchone()
    if not row:
        print(f"\nEntry {entry_id} not found.")
        input("[Enter]")
        return

    print(CLEAR, end="")
    col   = STATUS_COLOR.get(row["status"], "")
    label = STATUS_LABEL.get(row["status"], row["status"])
    print(f"{BOLD}── Entry {entry_id} ──────────────────────────────────────────{RESET}")
    print(f"Status:   {col}[{label}]{RESET}")
    print(f"Type:     {BOLD}{row['type']}{RESET}")
    dup = row["dup_count"] or 1
    if dup > 1:
        print(f"DupCount: {YELLOW}×{dup}{RESET}")
    fp = row["fingerprint"]
    if fp:
        print(f"FP:       {GREY}{fp}{RESET}")
    print(f"Source:   {row['source']}")
    print(f"Severity: {row['severity']}")
    print(f"Time:     {row['ts']}")
    if row["action_auto"]:
        print(f"Auto:     {CYAN}{row['action_auto']}{RESET}")
    if row["action_human"]:
        print(f"Human:    {GREEN}{row['action_human']}{RESET}")
    if row["ack_ts"]:
        print(f"ACK at:   {row['ack_ts']}")
    if row["ack_note"]:
        print(f"Note:     {row['ack_note']}")
    if row["autopilot_rule"]:
        rule = db.execute(
            "SELECT name, description, auto_action FROM autopilot_rules WHERE id=?",
            (row["autopilot_rule"],)
        ).fetchone()
        if rule:
            print(f"\n{BOLD}── Autopilot rule applied ──{RESET}")
            print(f"  Name:   {rule['name']}")
            print(f"  Desc:   {rule['description']}")
            print(f"  Action: {rule['auto_action']}")

    # ── Agent note (procedure checklist) ──────────────────────────────────────
    if row["agent_note"]:
        print(f"\n{BOLD}── Agent note / Procedure ──────────────────────────────{RESET}")
        print(f"  {row['agent_note']}")

    # ── Parsed payload ────────────────────────────────────────────────────────
    print(f"\n{BOLD}── Payload ─────────────────────────────────────────────────{RESET}")
    try:
        payload = json.loads(row["payload"])
        # Highlight key fields by event type
        _highlight_payload(payload, row["type"])
    except Exception:
        print(row["payload"])

    # ── Recent events from same source ────────────────────────────────────────
    history = db.execute(
        "SELECT id,ts,type,severity,status FROM algedonic_ledger "
        "WHERE source=? AND id!=? ORDER BY id DESC LIMIT 5",
        (row["source"], entry_id)
    ).fetchall()
    if history:
        print(f"\n{BOLD}── Recent events from '{row['source']}' ─────────────────────{RESET}")
        for h in history:
            hcol = STATUS_COLOR.get(h["status"], "")
            print(f"  id={h['id']}  {hcol}[{STATUS_LABEL.get(h['status'], h['status'])}]{RESET}"
                  f"  sev={h['severity']:.1f}  {h['type']}  {h['ts'][:19]}")

    print(f"\n{BOLD}── Actions ─────────────────────────────────────────────────{RESET}")
    print(f"  {BOLD}a{RESET} ACK (with optional note — describe what you did or decided)")
    print(f"  {BOLD}r{RESET} Reject (false positive / disagree with autopilot)")
    print(f"  {BOLD}d{RESET} Defer (acknowledge you saw it; will decide later)")
    print(f"  {BOLD}b{RESET} Back to list")
    print()

    while True:
        try:
            cmd = input(f"[{entry_id}]> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd == "b" or not cmd:
            break
        elif cmd == "a":
            ack_entry(db, entry_id, reject=False)
            break
        elif cmd == "r":
            ack_entry(db, entry_id, reject=True)
            break
        elif cmd == "d":
            defer_entry(db, entry_id)
            break
        else:
            print(f"  a=ACK  r=Reject  d=Defer  b=Back")


def _highlight_payload(payload: dict, etype: str) -> None:
    """Print payload with highlighted key fields for common event types."""
    import json

    KEY_FIELDS = {
        "covenant_halt":       ["reason", "streak", "sc", "tick", "source"],
        "drift_alert":         ["signal_status", "stasis_cos", "trust", "tick"],
        "semantic_divergence": ["claimed_cos", "recomputed_cos", "diff", "epsilon"],
        "emit_silence":        ["broker_in_msgs", "nucleus_event_count", "gap_s"],
        "merkle_break":        ["expected_hash", "actual_hash", "chain_id"],
        "invariant_breach":    ["invariant", "value", "threshold"],
    }

    keys_to_highlight = KEY_FIELDS.get(etype, [])
    highlighted = {}
    rest = {}

    def flatten(d, prefix=""):
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                flatten(v, full)
            else:
                short = k
                if short in keys_to_highlight or full in keys_to_highlight:
                    highlighted[full] = v
                else:
                    rest[full] = v

    flatten(payload)

    if highlighted:
        print(f"  {BOLD}Key fields:{RESET}")
        for k, v in highlighted.items():
            print(f"    {YELLOW}{k}{RESET} = {v}")

    print(f"  {BOLD}Full payload:{RESET}")
    print("  " + json.dumps(payload, indent=2).replace("\n", "\n  "))


def show_help(db: sqlite3.Connection) -> None:
    """Display help: commands + known event types + payload structure."""
    print(CLEAR, end="")
    print(f"{BOLD}VSF S5 Algedonic TUI — Ayuda{RESET}\n")

    print(f"{BOLD}── Comandos ─────────────────────────────────────────────────{RESET}")
    cmds = [
        ("a <id>",      "ACK — confirmar evento. Incluye nota describiendo tu decisión/acción."),
        ("r <id>",      "Reject — falso positivo o desacuerdo con autopiloto."),
        ("d <id>",      "Defer — viste el evento pero decides después. Queda visible."),
        ("p <id>",      "Detail — payload completo + historial de esa fuente + regla aplicada."),
        ("f pending",   "Filtrar: solo pending_human (los que esperan tu decisión)."),
        ("f deferred",  "Filtrar: solo diferidos."),
        ("f auto",      "Filtrar: solo auto_handled."),
        ("f all",       "Mostrar todo (sin filtro)."),
        ("l <N>",       "Límite de filas (default 40). Ej: l 100"),
        ("h",           "Esta ayuda."),
        ("q",           "Salir."),
    ]
    for cmd, desc in cmds:
        print(f"  {BOLD}{cmd:<14}{RESET} {desc}")

    print(f"\n{BOLD}── Tipos de evento y qué significan ─────────────────────────{RESET}")
    events = [
        ("covenant_halt",       "S5",  "El covenant detuvo la autonomía de S3. Requiere ACK para restaurar."),
        ("semantic_divergence", "S3*", "El shadow_recompute detectó que el stasis_cos reportado no coincide con el calculado."),
        ("emit_silence",        "S3*", "El núcleo dejó de emitir eventos — broker_probe detectó silencio."),
        ("merkle_break",        "S3*", "Rotura en la cadena Merkle de events.jsonl — integridad comprometida."),
        ("drift_alert",         "S3",  "stasis_cos cayó bajo umbral. Señal de degradación. Baja severidad = auto_handled."),
        ("invariant_breach",    "S3",  "VAR-1 / TRUST-1 / ALG-1 violado. Revisar métricas del núcleo."),
        ("signal_escalated",    "S3",  "S3 escaló señal por persistencia. El operador debe evaluar tendencia."),
        ("cycle_summary",       "S4",  "Resumen de ciclo S4 (informativo, baja prioridad)."),
    ]
    for etype, src, desc in events:
        sev_color = RED if src == "S5" else YELLOW if src == "S3*" else ""
        print(f"  {sev_color}{BOLD}{etype:<24}{RESET} [{src}] {desc}")

    print(f"\n{BOLD}── Semántica de la decisión ─────────────────────────────────{RESET}")
    print("  ACK     = 'Visto, procesado, no hay más que hacer.' La nota documenta tu decisión.")
    print("  Reject  = 'Falso positivo / la regla se equivocó.' Retroalimenta la política S5.")
    print("  Defer   = 'Estoy al tanto, decido después.' El evento queda visible con [DEFER].")
    print()
    print(f"  Beer: el algedónico exige RESPUESTA. No puedes ignorarlo indefinidamente.")
    print(f"  El ledger es APPEND-ONLY — ninguna entrada se borra jamás.")
    print()
    input("[Enter para volver]")


def defer_entry(db: sqlite3.Connection, entry_id: int) -> None:
    row = db.execute("SELECT status FROM algedonic_ledger WHERE id=?", (entry_id,)).fetchone()
    if not row:
        print(f"Entry {entry_id} not found.")
        input("[Enter]")
        return
    if row["status"] in ("acked", "rejected"):
        print(f"Entry {entry_id} already closed ({row['status']}).")
        input("[Enter]")
        return
    note = input("Defer note (optional — why now, when will you decide?): ").strip() or None
    db.execute(
        "UPDATE algedonic_ledger SET status='deferred', ack_ts=?, ack_note=? WHERE id=?",
        (now_iso(), note, entry_id)
    )
    db.commit()
    print(f"{YELLOW}Entry {entry_id} → deferred{RESET}")
    import time; time.sleep(0.8)


def ack_entry(db: sqlite3.Connection, entry_id: int, reject: bool = False) -> None:
    row = db.execute("SELECT status FROM algedonic_ledger WHERE id=?", (entry_id,)).fetchone()
    if not row:
        print(f"Entry {entry_id} not found.")
        input("[Enter]")
        return
    if row["status"] in ("acked", "rejected"):
        print(f"Entry {entry_id} already {row['status']}.")
        input("[Enter]")
        return

    new_status = "rejected" if reject else "acked"
    note = input(f"Note (optional): ").strip() or None
    db.execute(
        "UPDATE algedonic_ledger SET status=?, ack_ts=?, ack_note=?, action_human=? WHERE id=?",
        (new_status, now_iso(), note, f"human:{new_status}", entry_id)
    )
    db.commit()
    print(f"{GREEN if not reject else GREY}Entry {entry_id} → {new_status}{RESET}")
    import time; time.sleep(0.8)


def main():
    db = open_db()
    filter_status = None
    limit = 40

    while True:
        render(db, filter_status, limit)
        try:
            cmd = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not cmd:
            continue
        parts = cmd.split(None, 2)
        verb  = parts[0].lower()

        if verb == "q":
            break
        elif verb == "h":
            show_help(db)
        elif verb == "a" and len(parts) >= 2:
            try:
                ack_entry(db, int(parts[1]), reject=False)
            except ValueError:
                pass
        elif verb == "r" and len(parts) >= 2:
            try:
                ack_entry(db, int(parts[1]), reject=True)
            except ValueError:
                pass
        elif verb == "d" and len(parts) >= 2:
            try:
                defer_entry(db, int(parts[1]))
            except ValueError:
                pass
        elif verb in ("p", "i", "detail") and len(parts) >= 2:
            try:
                show_detail(db, int(parts[1]))
            except ValueError:
                pass
        elif verb == "f" and len(parts) >= 2:
            arg = parts[1].lower()
            filter_status = None if arg == "all" else arg
        elif verb == "l" and len(parts) >= 2:
            try:
                limit = int(parts[1])
            except ValueError:
                pass
        else:
            print(f"Unknown command — escriba 'h' para ayuda.")
            import time; time.sleep(0.5)


if __name__ == "__main__":
    main()
