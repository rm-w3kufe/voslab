#!/usr/bin/env python3
# design: docs/plans/runner_telemetry_api_design_2026_10_23.vsm v1.1 (ACTIVE)
#         + system/kernel/modules/runner_api_server.vsm
# ROL: S2
# DRIVER: event_coordinator
# CANAL: manual
# ROUTE: scripts route manifest (registered regen 2026-10-23); entry point:
#        python3 scripts/state/runner_api_server.py [--port 9090] [--once]
#        backbone route: staging server localhost (loopback only, R17-safe)
"""runner_api_server.py — staging server v1 por DESIGN v1.1.

- stdlib puro (ThreadingHTTPServer). loopback ONLY: si --port-genérico
  bind no-loopback => exit 2 (security_tier assertion fail-fast).
- POST /api/v1/cycles  idempotente por (agent_id, cycle_n) — dedupe JSONL.
- POST /api/v1/agents  registro {agent_id, os, arch, hostclass}.
- GET  /api/v1/health  rc 200 solo si puede abrir append store.
- Fail-open del lado del REPORTER (_cliente_) — server nunca bloquea.
  persistencia: state/runner_api/cycles.jsonl (lines selladas con
  server_received_ts). R17-safe: solo escribe SU STORE jsonl.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "state" / "runner_api"
CYCLES = STORE / "cycles.jsonl"
AGENTS = STORE / "agents.jsonl"

MEDIDA = "run steps: max 16; tail cap 4000 chars server-side; body max 1MiB"
LOCK = threading.Lock()


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append(path: Path, row: dict) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    with LOCK, path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for l in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if l.strip():
            try:
                out.append(json.loads(l))
            except ValueError:
                continue
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "runner-api/1.0"

    def log_message(self, fmt, *a):  # silencio al stderr; registro vía JSONL
        pass

    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802 (stdlib API)
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/v1/health":
            try:
                STORE.mkdir(parents=True, exist_ok=True)
                probe = STORE / ".health"
                now = _utc()
                probe.write_text(now)
                self._send(200, {"status": "ok", "ping": now})
            except OSError as e:
                self._send(503, {"status": "storage-error", "detail": str(e)[:160]})
            return
        if u.path == "/api/v1/cycles":
            rows = _read_jsonl(CYCLES)
            rows.sort(key=lambda r: (r.get("agent_id", ""), r.get("cycle_n", 0)),
                      reverse=True)
            q = urllib.parse.parse_qs(u.query)
            try:
                limit = min(200, int(q.get("limit", ["200"])[0]))
            except ValueError:
                limit = 200
            self._send(200, {"count": min(limit, len(rows)), "data": rows[:limit]})
            return
        if u.path.startswith("/api/v1/cycles/"):
            try:
                n = int(u.path.rsplit("/", 1)[1])
            except ValueError:
                self._send(400, {"error": "cycle_n esperado numérico"})
                return
            rows = [r for r in _read_jsonl(CYCLES) if r.get("cycle_n") == n]
            self._send(200, {"cycle_n": n, "data": rows})
            return
        self._send(404, {"error": "ruta desconocida"})

    def do_POST(self):  # noqa: N802 (stdlib API)
        if self.headers.get("Content-Length") is None:
            self._send(400, {"error": "Content-Length requerido"})
            return
        try:
            clen = int(self.headers["Content-Length"])
        except ValueError:
            self._send(400, {"error": "Content-Length inválido"})
            return
        if clen > 1_048_576:
            self._send(413, {"error": "body > 1MiB"})
            return
        try:
            body = json.loads(self.rfile.read(clen))
            if not isinstance(body, dict):
                raise ValueError("body debe ser objeto")
        except (ValueError, OSError) as e:
            self._send(400, {"error": f"JSON inválido: {str(e)[:120]}"})
            return

        if self.path == "/api/v1/agents":
            aid = body.get("agent_id", "")
            if not isinstance(aid, str) or not aid.startswith("vsf-"):
                self._send(400, {"error": "agent_id debe startswith 'vsf-'"})
                return
            row = {**body, "server_received_ts": _utc()}
            _append(AGENTS, row)
            self._send(201, {"status": "registered", "agent_id": aid})
            return

        if self.path == "/api/v1/cycles":
            agent_hdr = self.headers.get("X-VOS-Agent", "")
            if agent_hdr != body.get("agent_id"):
                self._send(403, {"error": "agent_id header vs payload mismatch"})
                return
            req = ["api", "producer", "agent_id", "cycle_n", "ts", "wall_s", "ok", "steps"]
            miss = [k for k in req if k not in body]
            if miss:
                self._send(400, {"error": "campos requeridos ausentes", "missing": miss})
                return
            steps = body["steps"]
            if not isinstance(steps, list) or len(steps) > 16:
                self._send(422, {"error": "steps debe ser lista <= 16"})
                return
            for s in steps:
                if isinstance(s, dict) and "tail" in s and isinstance(s["tail"], str):
                    s["tail"] = s["tail"][:4000]
            cycle_n = body["cycle_n"]
            if not isinstance(cycle_n, int) or cycle_n < 1:
                self._send(400, {"error": "cycle_n entero >= 1"})
                return
            dup = any(r.get("agent_id") == body.get("agent_id")
                      and r.get("cycle_n") == cycle_n
                      for r in _read_jsonl(CYCLES))
            if dup:
                self._send(200, {"status": "duplicate", "cycle_n": cycle_n})
                return
            row = {**body, "server_received_ts": _utc()}
            _append(CYCLES, row)
            self._send(201, {"status": "created", "cycle_n": cycle_n})
            return

        self._send(404, {"error": "ruta desconocida"})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9090)
    ap.add_argument("--bind", default="127.0.0.1",
                    help="SECURITY_TIER: solo loopback — cualquier otra "
                         "dirección exige TLS+token (design v1.1) — "
                         "no implementado => exit 2.")
    args = ap.parse_args()
    if args.bind not in ("127.0.0.1", "localhost", "::1"):
        print(json.dumps({"event": "assert-fail",
                          "detail": "bind fuera de loopback REQUERIRÍA "
                                    "security_tier (TLS+token) — v1 staging "
                                    "no posee auth fuerte (S5 ratificado "
                                    "2026-10-23). Server REFUSA arranque.",
                          "rc": 2}), file=sys.stderr)
        return 2
    srv = ThreadingHTTPServer((args.bind, args.port), Handler)
    srv.daemon_threads = True
    print(json.dumps({"event": "runner-api-listening",
                      "endpoint": f"http://{args.bind}:{args.port}",
                      "server_received_store": str(CYCLES)}), flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
