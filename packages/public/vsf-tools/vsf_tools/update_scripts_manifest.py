#!/usr/bin/env python3
"""
update_scripts_manifest.py — Regenerates the scripts manifests (vOSlab).

Usage:
    python3 scripts/shared/update_scripts_manifest.py

Outputs TWO manifests:
  1. scripts_state_manifest.vsm — structure of scripts/state/ (legacy shape)
  2. scripts_manifest.vsm       — FULL scripts corpus census
     (S5 order 2026-10-02: the ~/vsf/scripts tree migrated to vOSlab;
      nothing runs from ~/vsf. Machine contract: `family:<name>:<count>`
      plus `file:<family>/<path>:<sha16>` lines.)

Workspace is detected by walking up for current_focus.json (no
hardcoded usernames; clone-portable).
"""

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone


def _workspace() -> Path:
    """Walk up from this file looking for current_focus.json."""
    here = Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "current_focus.json").exists():
            return cand
    # Fallback: scripts/shared/ lives two levels under the workspace
    return here.parent.parent.parent


WS = _workspace()
SCRIPTS_DIR = WS / "scripts" / "state"
MANIFEST_FILE = WS / "system" / "instance" / "vsf-instance-v1" / \
    "scripts_state_manifest.vsm"
CORPUS_MANIFEST_FILE = WS / "system" / "instance" / "vsf-instance-v1" / \
    "scripts_manifest.vsm"
CORPUS_DIR = WS / "scripts"

# Extensiones a incluir
EXTENSIONS = {'.py', '.sh', '.service', '.timer', '.sql', '.json', '.db'}

# Directorios a excluir
EXCLUDE_DIRS = {'__pycache__', '.git', 'node_modules'}

def scan_directory(directory: Path) -> dict:
    """Escanea un directorio y retorna su contenido."""
    result = {}
    
    for item in sorted(directory.iterdir()):
        if item.is_dir() and item.name not in EXCLUDE_DIRS:
            subdir_result = scan_directory(item)
            if subdir_result:
                result[item.name] = subdir_result
        elif item.is_file() and item.suffix in EXTENSIONS:
            if directory.name not in result:
                result[directory.name] = []
            result[directory.name].append(item.name)
    
    return result

def get_dependencies(files: list) -> list:
    """Analyze basic file dependencies."""
    deps = []
    for f in files:
        if f.endswith('.py'):
            deps.append("python")
        elif f.endswith('.sh'):
            deps.append("bash")
        elif f.endswith('.sql'):
            deps.append("sqlite3")
        elif f.endswith('.service') or f.endswith('.timer'):
            deps.append("systemd")
    return list(set(deps))

def generate_manifest(structure: dict) -> str:
    """Generate the manifest content."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    manifest = f"""⟦ scripts_state_manifest | SCRIPTS-STATE-MANIFEST-v1 | vsm-1.2.1 | {now} ⟧

@vsm 1.2.1
@status active

// ═══════════════════════════════════════════════════════════════════════════
// SCRIPTS/STATE/ MANIFEST
// scripts/state/ MANIFEST — registry of all files and their dependencies
// ═══════════════════════════════════════════════════════════════════════════

// PURPOSE
// ═══════════════════════════════════════════════════════════════════════════
//
// This manifest documents the structure of scripts/state/ and its
// dependencies. It is updated automatically when scripts are modified.
//
// ═══════════════════════════════════════════════════════════════════════════
// STRUCTURE
// ═══════════════════════════════════════════════════════════════════════════

estructura() {{
"""
    
    for dir_name, content in structure.items():
        if isinstance(content, dict):
            # Subdirectorio
            manifest += f"  {dir_name}: {{\n"
            manifest += f"    files: [\n"
            for sub_item, sub_content in content.items():
                if isinstance(sub_content, list):
                    for f in sub_content:
                        manifest += f'      "{sub_item}/{f}",\n'
            manifest += f"    ],\n"
            deps = get_dependencies([f for sub_content in content.values() if isinstance(sub_content, list) for f in sub_content])
            manifest += f"    dependencies: {deps},\n"
            manifest += f"  }},\n"
        elif isinstance(content, list):
            # Archivos directos
            manifest += f"  {dir_name}: {{\n"
            manifest += f"    files: [\n"
            for f in content:
                manifest += f'      "{f}",\n'
            manifest += f"    ],\n"
            deps = get_dependencies(content)
            manifest += f"    dependencies: {deps},\n"
            manifest += f"  }},\n"
    
    manifest += """}

// ═══════════════════════════════════════════════════════════════════════════
// AUTOMATIC UPDATE
// ═══════════════════════════════════════════════════════════════════════════

automatic_update() {
  script: "scripts/shared/update_scripts_manifest.py",
  usage: "Run after modifying scripts/state/ to update this manifest",
  command: "python3 scripts/shared/update_scripts_manifest.py",
}

// ═══════════════════════════════════════════════════════════════════════════
// VERIFICATION
// ═══════════════════════════════════════════════════════════════════════════

verification() {
  checks: [
    "1. All listed files exist",
    "2. No unlisted files exist under scripts/state/",
    "3. Dependencies are wired correctly",
  ],
  commands: [
    "python3 scripts/shared/verify_scripts_manifest.py → PASS",
    "grep -rn 'scripts/state/' checks/ | grep -v '# →' → EMPTY",
  ],
}

"""
    manifest += f"⟦ /scripts_state_manifest ⟧\n"
    
    return manifest

def count_files(structure: dict) -> int:
    """Count the total number of files in the structure."""
    count = 0
    for value in structure.values():
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += count_files(value)
    return count


# ─── Full corpus census (S5 2026-10-02: scripts live in vOSlab) ─────────────

def _now_iso() -> str:
    """Real UTC timestamp, never :00 seconds/minutes or T00: (vsm gate)."""
    t = datetime.now(timezone.utc)
    while t.second == 0 or t.minute == 0 or t.hour == 0:
        t = datetime.now(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def scan_corpus() -> dict:
    """Scan scripts/ — {family: [(relpath, sha16), ...]} sorted, deterministic.

    Families = top-level dirs (minus EXCLUDE_DIRS); `_root` collects
    top-level script files directly under scripts/.
    """
    out: dict = {}
    for entry in sorted(CORPUS_DIR.iterdir()):
        if entry.name.startswith(".") or entry.name in EXCLUDE_DIRS:
            continue
        if entry.is_dir():
            files = []
            for f in sorted(entry.rglob("*")):
                if f.is_file() and f.suffix in EXTENSIONS and \
                        not any(p in EXCLUDE_DIRS for p in f.parts):
                    files.append((str(f.relative_to(CORPUS_DIR)),
                                  _sha16(f)))
            if files:
                out[entry.name] = files
        elif entry.is_file() and entry.suffix in EXTENSIONS:
            out.setdefault("_root", []).append((entry.name, _sha16(entry)))
    return out


def generate_corpus_manifest(corpus: dict) -> str:
    """Render the full-corpus .vsm manifest (machine contract lines)."""
    families = [k for k in corpus if k != "_root"]
    total = sum(len(v) for v in corpus.values())
    lines = [
        f"⟦ scripts_manifest | SCRIPTS-MANIFEST-v1 | vsm-1.2.1 | {_now_iso()} ⟧",
        "",
        "@vsm 1.2.1",
        "@status active",
        "",
        "// ═════════════════════════════════════════════════════════════════",
        "// FULL SCRIPTS CORPUS CENSUS",
        "// Machine contract: family:<name>:<count> and",
        "// file:<family>/<path>:<sha16>. Regenerate:",
        "//   python3 scripts/shared/update_scripts_manifest.py",
        "// S5 2026-10-02: ~/vsf/scripts migrated here — nothing runs from",
        "// ~/vsf. Consumed by predicate scripts_corpus_manifest_ok (RSI).",
        "// ═════════════════════════════════════════════════════════════════",
        "",
        f"families: {len(families)}  files: {total}",
        "",
    ]
    for fam in sorted(corpus):
        files = corpus[fam]
        lines.append(f"family:{fam}:{len(files)}")
        for rel, sha in files:
            lines.append(f"file:{fam}/{rel}:{sha}" if fam != "_root"
                         else f"file:{rel}:{sha}")
        lines.append("")
    lines.append("⟦ /scripts_manifest ⟧")
    return "\n".join(lines) + "\n"


def main():
    """Main entry point — regenerates both manifests."""
    print(f"Scanning {SCRIPTS_DIR}...")
    structure = scan_directory(SCRIPTS_DIR)

    print("Generating state manifest...")
    manifest_content = generate_manifest(structure)

    print(f"Saving to {MANIFEST_FILE}...")
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(manifest_content)

    print("Scanning full corpus (scripts/)...")
    corpus = scan_corpus()
    print(f"Saving to {CORPUS_MANIFEST_FILE}...")
    CORPUS_MANIFEST_FILE.write_text(generate_corpus_manifest(corpus))

    print("✅ Manifests updated successfully")
    print(f"   state files: {count_files(structure)}  "
          f"corpus files: {sum(len(v) for v in corpus.values())}  "
          f"families: {len([k for k in corpus if k != '_root'])}")

if __name__ == "__main__":
    main()
