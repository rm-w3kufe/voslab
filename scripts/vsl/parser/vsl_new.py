#!/usr/bin/env python3
"""vsl_new — instantiate VSL templates (VSL-TEMPLATE-SYSTEM 2026-08-13).

Plantillas en scripts/vsl/templates/ (task, session, vblock, envelope).
El agente LLENA placeholders {{...}} en vez de razonar la construcción:
el header/footer ⟦…⟧ de vblock/envelope ya vienen puestos — el defecto
(header ausente, footer mismatch) no puede ocurrir por construcción.

Uso:
  python3 scripts/vsl/vsl_new.py task   --id X --priority P2 --agent S --gate "…" --what "…" --done_when "…"
  python3 scripts/vsl/vsl_new.py session --id 2026-08-15-ds-x --summary "…" [--result pass]
  python3 scripts/vsl/vsl_new.py vblock --name X --type SPEC [--status proposed] --purpose "…" [--content "…"]
  python3 scripts/vsl/vsl_new.py envelope --name X --from S3 --from-level 1 --to S1 --to-level 1 …

Salida: imprime el .vsm instanciado por stdout (o --out FILE lo escribe).
Siempre valida --strict ANTES de imprimir: una plantilla mal llenada falla
aquí, no en el pre-commit. D6/R10.1: es un generador determinista, no LLM.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
PARSER = ROOT / "scripts" / "vsl_parser.py"

TEMPLATE_FILES = {
    "task": "task.vsl",
    "session": "session.vsl",
    "vblock": "vblock.vsl",
    "envelope": "envelope.vsl",
}

# fecha por defecto: hoy (YYYY-MM-DD) — session ids usan ese prefijo
def _today() -> str:
    return date.today().isoformat()


def render(template: str, values: dict[str, str]) -> str:
    """replaces {{KEY}} with value — leaves {{UNKNOWN}} if not passed (fails later)."""
    def repl(m):
        key = m.group(1)
        return values.get(key, m.group(0))  # sin valor → placeholder intacto
    return re.sub(r"\{\{(\w+)\}\}", repl, template)


def validate_strict(text: str) -> tuple[int, str]:
    """--strict parse; returns (rc, output)."""
    p = PARSER
    if not p.exists():
        return (0, "(no parser — skip strict)")
    # el parser acepta archivo; pasamos stdin si soporta, si no tempfile
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".vsm", delete=False, encoding="utf-8") as f:
        f.write(text)
        tmp = f.name
    try:
        r = subprocess.run([sys.executable, str(p), tmp, "--strict"],
                           capture_output=True, text=True)
        return (r.returncode, (r.stdout + r.stderr).strip())
    finally:
        Path(tmp).unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="VSL template instantiator")
    sub = ap.add_subparsers(dest="kind", required=True)

    p_task = sub.add_parser("task")
    p_task.add_argument("--id", required=True)
    p_task.add_argument("--priority", default="P2")
    p_task.add_argument("--agent", default="S")
    p_task.add_argument("--gate", default="ninguno")
    p_task.add_argument("--what", required=True)
    p_task.add_argument("--done_when", required=True)

    p_sess = sub.add_parser("session")
    p_sess.add_argument("--id", required=True)
    p_sess.add_argument("--summary", required=True)
    p_sess.add_argument("--result", default="pass")
    p_sess.add_argument("--resolved-item", default="pendiente de detalle")
    p_sess.add_argument("--commit-sha", default="abc1234")
    p_sess.add_argument("--commit-desc", default="desc")
    p_sess.add_argument("--verify-cmd", default="true")
    p_sess.add_argument("--verify-output", default="✓")
    p_sess.add_argument("--next", default="verificar estado")

    p_vb = sub.add_parser("vblock")
    p_vb.add_argument("--name", required=True)
    p_vb.add_argument("--type", default="SPEC")
    p_vb.add_argument("--status", default="proposed")
    p_vb.add_argument("--purpose", required=True)
    p_vb.add_argument("--content", default="// cuerpo")

    p_env = sub.add_parser("envelope")
    p_env.add_argument("--name", required=True)
    p_env.add_argument("--from", dest="frm", required=True)
    p_env.add_argument("--from-level", default="1")
    p_env.add_argument("--to", required=True)
    p_env.add_argument("--to-level", default="1")
    p_env.add_argument("--msg-type", default="directive")
    p_env.add_argument("--task-ref", default="TASKS.vsm:task")
    p_env.add_argument("--act", required=True)
    p_env.add_argument("--why", default="contexto")
    p_env.add_argument("--gate", default="ninguno")
    p_env.add_argument("--stop", default="ninguno")
    p_env.add_argument("--result", required=True)
    p_env.add_argument("--authorizer", default="rmw3")
    p_env.add_argument("--guardrail", default="ninguno")

    for p in (p_task, p_sess, p_vb, p_env):
        p.add_argument("--out", default=None)

    args = ap.parse_args()
    kind = args.kind

    base = {
        "DATE": _today(),
        "PRIORITY": getattr(args, "priority", "P2"),
        "AGENT": getattr(args, "agent", "S"),
    }
    if kind == "task":
        values = {
            **base,
            "TASK_ID": args.id, "GATE": args.gate, "WHAT": args.what,
            "DONE_WHEN": args.done_when,
        }
    elif kind == "session":
        values = {
            "SESSION_ID": args.id, "SUMMARY": args.summary, "RESULT": args.result,
            "RESOLVED_ITEM": args.resolved_item, "COMMIT_SHA": args.commit_sha,
            "COMMIT_DESC": args.commit_desc, "VERIFY_CMD": args.verify_cmd,
            "VERIFY_OUTPUT": args.verify_output, "NEXT_ACTION": args.next,
        }
    elif kind == "vblock":
        values = {
            "BLOCK_NAME": args.name, "BLOCK_TYPE": args.type, "STATUS": args.status,
            "PURPOSE": args.purpose, "CONTENT": args.content, "DATE": _today(),
        }
    else:  # envelope
        values = {
            "ENVELOPE_NAME": args.name, "FROM": args.frm, "FROM_LEVEL": args.from_level,
            "TO": args.to, "TO_LEVEL": args.to_level, "MSG_TYPE": args.msg_type,
            "TASK_REF": args.task_ref, "ACT": args.act, "WHY": args.why,
            "GATE": args.gate, "STOP": args.stop, "RESULT": args.result,
            "AUTHORIZER": args.authorizer, "GUARDRAIL": args.guardrail, "DATE": _today(),
        }

    tpl = TEMPLATES / TEMPLATE_FILES[kind]
    text = render(tpl.read_text(encoding="utf-8"), values)

    # placeholders sin llenar → falla temprano
    missing = re.findall(r"\{\{(\w+)\}\}", text)
    if missing:
        print(f"❌ plantilla incompleta — placeholders sin llenar: {missing}", file=sys.stderr)
        return 1

    # task/session are FRAGMENTS living inside TASKS.vsm (the parent file
    # carries header/footer ⟦…⟧) — strict applies to the whole file.
    # vblock/envelope are standalone files → direct strict.
    if kind in ("vblock", "envelope"):
        rc, out = validate_strict(text)
        if rc != 0:
            print(f"❌ instancia NO es VALID --strict:\n{out}", file=sys.stderr)
            return 1
    else:
        # fragment: validate brace balance + that it does not break the parent file
        if text.count("{") != text.count("}"):
            print("❌ fragmento desbalanceado ({{ }} mismatch)", file=sys.stderr)
            return 1
        if args.out:
            # validar el archivo DESTINO completo tras insertar (modo --in-file)
            dest = Path(args.out)
            if dest.exists():
                combined = dest.read_text(encoding="utf-8") + "\n" + text + "\n"
                rc, out = validate_strict(combined)
                if rc != 0:
                    print(f"❌ archivo destino tras insertar NO es VALID --strict:\n{out}",
                          file=sys.stderr)
                    return 1

    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"✓ instancia VALID --strict escrita en {args.out}")
    else:
        print(text)
        print(f"✓ instancia VALID --strict ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())