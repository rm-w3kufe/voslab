"""
focus_extended.py — Extended focus tracking with hierarchy and agent attribution.

This module extends the basic focus tracking to include:
- Agent attribution (who is working on what)
- Task hierarchy (parent/child relationships)
- Context preservation (why, blockers, learnings)
- Subagent result references

SECURITY: Focus entries are persisted to maintain context across sessions.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict


@dataclass
class FocusEntry:
    """Extended focus entry with hierarchy and context."""
    
    ref: str
    status: str  # active | paused | done
    note: str
    started_at: str
    updated_at: str
    
    # New fields: Attribution
    agent_id: str
    
    # New fields: Hierarchy
    parent_ref: Optional[str]
    subtask_refs: List[str]
    
    # New fields: Context
    why: str
    blockers: List[str]
    learnings: List[str]
    
    # New fields: Subagent tracking
    subagent_refs: List[str]
    
    @staticmethod
    def now() -> str:
        """Get current timestamp in ISO 8601 format."""
        return datetime.now(timezone.utc).isoformat()


class ExtendedFocusTracker:
    """Extended focus tracking with hierarchy and context."""
    
    def __init__(self, focus_file: Optional[str] = None):
        """Initialize the tracker.
        
        Args:
            focus_file: Path to current_focus.json
                     If None, uses default location
        """
        if focus_file:
            self.focus_file = Path(focus_file)
        else:
            # Default location
            workspace = os.environ.get("VOS_WORKSPACE", os.environ.get("VOS_ROOT", os.getcwd()))
            self.focus_file = Path(workspace) / "current_focus.json"
        
        self.entries: Dict[str, FocusEntry] = {}
        self._load()
    
    def _load(self):
        """Load focus entries from file."""
        if not self.focus_file.exists():
            self.entries = {}
            return
        
        try:
            with open(self.focus_file, 'r') as f:
                data = json.load(f)
            
            for item in data:
                entry = FocusEntry(
                    ref=item["ref"],
                    status=item.get("status", "active"),
                    note=item.get("note", ""),
                    started_at=item.get("started_at", FocusEntry.now()),
                    updated_at=item.get("updated_at", FocusEntry.now()),
                    agent_id=item.get("agent_id", "unknown"),
                    parent_ref=item.get("parent_ref"),
                    subtask_refs=item.get("subtask_refs", []),
                    why=item.get("why", ""),
                    blockers=item.get("blockers", []),
                    learnings=item.get("learnings", []),
                    subagent_refs=item.get("subagent_refs", [])
                )
                self.entries[entry.ref] = entry
        except Exception as e:
            print(f"Warning: Failed to load focus file: {e}")
            self.entries = {}
    
    def _save(self):
        """Save focus entries to file."""
        data = [asdict(entry) for entry in self.entries.values()]
        
        # Ensure parent directory exists
        self.focus_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.focus_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def mark_active(
        self,
        ref: str,
        agent_id: str,
        note: str = "",
        parent_ref: Optional[str] = None,
        why: str = ""
    ) -> FocusEntry:
        """Mark a task as active.
        
        Args:
            ref: Task reference
            agent_id: Agent identifier
            note: Context note
            parent_ref: Parent task reference (optional)
            why: Reason this task was chosen
            
        Returns:
            FocusEntry
        """
        now = FocusEntry.now()
        
        if ref in self.entries:
            # Update existing entry
            entry = self.entries[ref]
            entry.status = "active"
            entry.note = note or entry.note
            entry.agent_id = agent_id
            entry.updated_at = now
            if parent_ref:
                entry.parent_ref = parent_ref
            if why:
                entry.why = why
        else:
            # Create new entry
            entry = FocusEntry(
                ref=ref,
                status="active",
                note=note,
                started_at=now,
                updated_at=now,
                agent_id=agent_id,
                parent_ref=parent_ref,
                subtask_refs=[],
                why=why,
                blockers=[],
                learnings=[],
                subagent_refs=[]
            )
            self.entries[ref] = entry
        
        # Add to parent's subtask_refs if parent exists
        if parent_ref and parent_ref in self.entries:
            parent = self.entries[parent_ref]
            if ref not in parent.subtask_refs:
                parent.subtask_refs.append(ref)
                parent.updated_at = now
        
        self._save()
        return entry
    
    def add_learning(self, ref: str, learning: str) -> bool:
        """Add a learning to a focus entry.
        
        Args:
            ref: Task reference
            learning: What was learned
            
        Returns:
            True if added, False if entry not found
        """
        if ref not in self.entries:
            return False
        
        entry = self.entries[ref]
        if learning not in entry.learnings:
            entry.learnings.append(learning)
            entry.updated_at = FocusEntry.now()
            self._save()
        
        return True
    
    def add_blocker(self, ref: str, blocker_ref: str) -> bool:
        """Add a blocker to a focus entry.
        
        Args:
            ref: Task reference
            blocker_ref: Blocking task reference
            
        Returns:
            True if added, False if entry not found
        """
        if ref not in self.entries:
            return False
        
        entry = self.entries[ref]
        if blocker_ref not in entry.blockers:
            entry.blockers.append(blocker_ref)
            entry.updated_at = FocusEntry.now()
            self._save()
        
        return True
    
    def remove_blocker(self, ref: str, blocker_ref: str) -> bool:
        """Remove a blocker from a focus entry.
        
        Args:
            ref: Task reference
            blocker_ref: Blocking task reference to remove
            
        Returns:
            True if removed, False if entry not found
        """
        if ref not in self.entries:
            return False
        
        entry = self.entries[ref]
        if blocker_ref in entry.blockers:
            entry.blockers.remove(blocker_ref)
            entry.updated_at = FocusEntry.now()
            self._save()
        
        return True
    
    def add_subagent_ref(self, ref: str, subagent_ref: str) -> bool:
        """Add a subagent result reference.
        
        Args:
            ref: Task reference
            subagent_ref: Subagent result reference
            
        Returns:
            True if added, False if entry not found
        """
        if ref not in self.entries:
            return False
        
        entry = self.entries[ref]
        if subagent_ref not in entry.subagent_refs:
            entry.subagent_refs.append(subagent_ref)
            entry.updated_at = FocusEntry.now()
            self._save()
        
        return True
    
    def mark_done(self, ref: str, note: str = "") -> bool:
        """Mark a task as done.
        
        Args:
            ref: Task reference
            note: Final note
            
        Returns:
            True if marked, False if entry not found
        """
        if ref not in self.entries:
            return False
        
        entry = self.entries[ref]
        entry.status = "done"
        if note:
            entry.note = note
        entry.updated_at = FocusEntry.now()
        self._save()
        
        return True
    
    def get_active_tasks(self, agent_id: Optional[str] = None) -> List[FocusEntry]:
        """Get all active tasks.
        
        Args:
            agent_id: Filter by agent (optional)
            
        Returns:
            List of active FocusEntry objects
        """
        active = [e for e in self.entries.values() if e.status == "active"]
        
        if agent_id:
            active = [e for e in active if e.agent_id == agent_id]
        
        return active
    
    def get_task_hierarchy(self, ref: str) -> Dict:
        """Get task hierarchy starting from a reference.
        
        Args:
            ref: Task reference
            
        Returns:
            Dict with task and its subtasks
        """
        if ref not in self.entries:
            return {}
        
        entry = self.entries[ref]
        hierarchy = {
            "ref": entry.ref,
            "status": entry.status,
            "agent_id": entry.agent_id,
            "note": entry.note,
            "subtasks": []
        }
        
        for subtask_ref in entry.subtask_refs:
            subtask_hierarchy = self.get_task_hierarchy(subtask_ref)
            if subtask_hierarchy:
                hierarchy["subtasks"].append(subtask_hierarchy)
        
        return hierarchy
    
    def get_entry(self, ref: str) -> Optional[FocusEntry]:
        """Get a specific focus entry.
        
        Args:
            ref: Task reference
            
        Returns:
            FocusEntry or None if not found
        """
        return self.entries.get(ref)
    
    def list_entries(self) -> List[Dict]:
        """List all focus entries as dicts.
        
        Returns:
            List of focus entry dicts
        """
        return [asdict(entry) for entry in self.entries.values()]


# Singleton instance
_tracker = None

def get_tracker(focus_file: Optional[str] = None) -> ExtendedFocusTracker:
    """Get or create the global focus tracker."""
    global _tracker
    if _tracker is None:
        _tracker = ExtendedFocusTracker(focus_file)
    return _tracker


def mark_active(
    ref: str,
    agent_id: str,
    note: str = "",
    parent_ref: Optional[str] = None,
    why: str = ""
) -> Dict:
    """Convenience function to mark a task as active.
    
    Args:
        ref: Task reference
        agent_id: Agent identifier
        note: Context note
        parent_ref: Parent task reference (optional)
        why: Reason this task was chosen
        
    Returns:
        Focus entry dict
    """
    tracker = get_tracker()
    entry = tracker.mark_active(ref, agent_id, note, parent_ref, why)
    return asdict(entry)


def add_learning(ref: str, learning: str) -> bool:
    """Convenience function to add a learning."""
    tracker = get_tracker()
    return tracker.add_learning(ref, learning)


def add_blocker(ref: str, blocker_ref: str) -> bool:
    """Convenience function to add a blocker."""
    tracker = get_tracker()
    return tracker.add_blocker(ref, blocker_ref)


def get_active_tasks(agent_id: Optional[str] = None) -> List[Dict]:
    """Convenience function to get active tasks."""
    tracker = get_tracker()
    entries = tracker.get_active_tasks(agent_id)
    return [asdict(e) for e in entries]


# CLI entry point
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "list":
            tracker = get_tracker()
            entries = tracker.list_entries()
            print(json.dumps(entries, indent=2))
        
        elif command == "active":
            agent_id = sys.argv[2] if len(sys.argv) > 2 else None
            entries = get_active_tasks(agent_id)
            print(json.dumps(entries, indent=2))
        
        elif command == "hierarchy":
            ref = sys.argv[2] if len(sys.argv) > 2 else ""
            tracker = get_tracker()
            hierarchy = tracker.get_task_hierarchy(ref)
            print(json.dumps(hierarchy, indent=2))
        
        else:
            print(f"Unknown command: {command}")
            print("Available commands: list, active, hierarchy")
    
    else:
        print("Extended Focus Tracker")
        print("Usage: focus_extended.py <command> [args]")
        print("Commands:")
        print("  list - List all focus entries")
        print("  active [agent_id] - List active tasks")
        print("  hierarchy <ref> - Get task hierarchy")
