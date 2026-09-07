"""surgery_mode.py — Surgery mode toggle for pipeline bypass.

Ported from child/scripts/helpers/surgery_mode.sh.
Provides Python interface for enabling/disabling surgery mode
which bypasses pipeline predicates during intensive editing.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class SurgeryMode:
    """Manages surgery mode state and history."""
    
    def __init__(self, workspace_dir: str | Path | None = None):
        """Initialize surgery mode manager.
        
        Args:
            workspace_dir: Path to workspace directory (default: current dir)
        """
        if workspace_dir is None:
            workspace_dir = Path.cwd()
        self.workspace_dir = Path(workspace_dir)
        self.flag_file = self.workspace_dir / ".surgery_mode"
        self.history_dir = self.workspace_dir / "state"
        self.history_file = self.history_dir / "surgery_history.jsonl"
        self.safety_timeout_min = int(os.environ.get("VSF_SURGERY_TIMEOUT_MIN", "60"))
        
        # Ensure history directory exists
        self.history_dir.mkdir(parents=True, exist_ok=True)
    
    def _log_history(self, action: str, extra: Dict[str, Any] | None = None) -> None:
        """Log an action to history file."""
        entry = {
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            entry.update(extra)
        
        with open(self.history_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    
    def _get_flag_age_minutes(self) -> int:
        """Get age of flag file in minutes."""
        if not self.flag_file.exists():
            return 0
        flag_time = self.flag_file.stat().st_mtime
        current_time = time.time()
        return int((current_time - flag_time) / 60)
    
    def enable(self) -> Dict[str, Any]:
        """Enable surgery mode."""
        self.flag_file.touch()
        self._log_history("enabled", {"timeout_min": self.safety_timeout_min})
        return {
            "status": "enabled",
            "flag": str(self.flag_file),
            "timeout_min": self.safety_timeout_min,
        }
    
    def disable(self) -> Dict[str, Any]:
        """Disable surgery mode."""
        if not self.flag_file.exists():
            return {"status": "already_off"}
        
        age = self._get_flag_age_minutes()
        self._log_history("disabled", {"duration_min": age})
        self.flag_file.unlink()
        return {
            "status": "disabled",
            "duration_min": age,
        }
    
    def status(self) -> Dict[str, Any]:
        """Check surgery mode status."""
        if not self.flag_file.exists():
            return {"status": "inactive"}
        
        age = self._get_flag_age_minutes()
        result = {
            "status": "active",
            "flag": str(self.flag_file),
            "age_min": age,
            "timeout_min": self.safety_timeout_min,
        }
        
        if age > self.safety_timeout_min:
            result["warning"] = f"Active for > {self.safety_timeout_min} minutes"
        
        return result
    
    def check(self) -> Dict[str, Any]:
        """Check status and auto-disable if stale."""
        if not self.flag_file.exists():
            return {"status": "inactive"}
        
        age = self._get_flag_age_minutes()
        if age > self.safety_timeout_min:
            self._log_history("auto-disabled", {
                "duration_min": age,
                "timeout": self.safety_timeout_min,
            })
            self.flag_file.unlink()
            return {
                "status": "auto_disabled",
                "duration_min": age,
                "timeout_min": self.safety_timeout_min,
            }
        
        return {
            "status": "active",
            "age_min": age,
            "timeout_min": self.safety_timeout_min,
        }
    
    def history(self) -> list[Dict[str, Any]]:
        """Get activation history."""
        if not self.history_file.exists():
            return []
        
        history = []
        with open(self.history_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        history.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return history
    
    def is_active(self) -> bool:
        """Check if surgery mode is currently active."""
        return self.flag_file.exists()


# Convenience functions
def enable(workspace_dir: str | Path | None = None) -> Dict[str, Any]:
    """Enable surgery mode."""
    return SurgeryMode(workspace_dir).enable()


def disable(workspace_dir: str | Path | None = None) -> Dict[str, Any]:
    """Disable surgery mode."""
    return SurgeryMode(workspace_dir).disable()


def status(workspace_dir: str | Path | None = None) -> Dict[str, Any]:
    """Check surgery mode status."""
    return SurgeryMode(workspace_dir).status()


def is_active(workspace_dir: str | Path | None = None) -> bool:
    """Check if surgery mode is active."""
    return SurgeryMode(workspace_dir).is_active()
