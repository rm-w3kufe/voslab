"""
agent_results.py — Persistent storage for subagent conclusions.

This module provides:
- Storage for agent task results
- Querying agent conclusions
- Reusability tracking
- Cross-session knowledge accumulation

SECURITY: Agent results are persisted to avoid re-doing work.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import hashlib


@dataclass
class AgentResult:
    """Result from a subagent task execution."""
    
    id: str
    agent_id: str
    task_ref: str
    parent_task_ref: Optional[str]
    
    # What was the task?
    task_description: str
    
    # What did the agent conclude?
    conclusion: str
    evidence: List[str]
    
    # What was the outcome?
    outcome: str  # success | partial | failure
    duration_ms: int
    
    # Timestamps
    started_at: str
    completed_at: str
    
    # Reusability
    reusable: bool
    reuse_count: int
    last_reused_at: Optional[str]
    
    @staticmethod
    def create_id(agent_id: str, task_ref: str) -> str:
        """Create a deterministic ID for an agent result."""
        data = f"{agent_id}|{task_ref}"
        return hashlib.sha256(data.encode()).hexdigest()[:12]
    
    @staticmethod
    def now() -> str:
        """Get current timestamp in ISO 8601 format."""
        return datetime.now(timezone.utc).isoformat()


class AgentResultsStore:
    """Persistent storage for agent results."""
    
    def __init__(self, base_dir: Optional[str] = None):
        """Initialize the store.
        
        Args:
            base_dir: Base directory for agent results.
                     If None, uses VOS_AGENT_STATE_DIR or ~/.vos/agents/
        """
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            agent_state_dir = os.environ.get("VOS_AGENT_STATE_DIR")
            if agent_state_dir:
                self.base_dir = Path(agent_state_dir).parent
            else:
                self.base_dir = Path.home() / ".vos" / "agents"
        
        self.results_dir = self.base_dir / "shared" / "agent_results"
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_agent_dir(self, agent_id: str) -> Path:
        """Get directory for a specific agent."""
        agent_dir = self.base_dir / agent_id / "results"
        agent_dir.mkdir(parents=True, exist_ok=True)
        return agent_dir
    
    def store_result(self, result: AgentResult) -> str:
        """Store an agent result.
        
        Args:
            result: AgentResult to store
            
        Returns:
            ID of stored result
        """
        agent_dir = self._get_agent_dir(result.agent_id)
        result_file = agent_dir / f"{result.id}.json"
        
        with open(result_file, 'w') as f:
            json.dump(asdict(result), f, indent=2)
        
        return result.id
    
    def get_result(self, agent_id: str, result_id: str) -> Optional[AgentResult]:
        """Get a specific agent result.
        
        Args:
            agent_id: Agent identifier
            result_id: Result identifier
            
        Returns:
            AgentResult or None if not found
        """
        agent_dir = self._get_agent_dir(agent_id)
        result_file = agent_dir / f"{result_id}.json"
        
        if not result_file.exists():
            return None
        
        with open(result_file, 'r') as f:
            data = json.load(f)
        
        return AgentResult(**data)
    
    def get_results_for_task(self, task_ref: str) -> List[AgentResult]:
        """Get all agent results for a specific task.
        
        Args:
            task_ref: Task reference
            
        Returns:
            List of AgentResult objects
        """
        results = []
        
        # Search all agents
        for agent_dir in self.base_dir.glob("*/results"):
            for result_file in agent_dir.glob("*.json"):
                try:
                    with open(result_file, 'r') as f:
                        data = json.load(f)
                    
                    if data.get("task_ref") == task_ref:
                        results.append(AgentResult(**data))
                except Exception:
                    continue
        
        return results
    
    def get_reusable_conclusions(self, min_reuse_count: int = 0) -> List[AgentResult]:
        """Get reusable agent conclusions.
        
        Args:
            min_reuse_count: Minimum reuse count to include
            
        Returns:
            List of reusable AgentResult objects
        """
        results = []
        
        # Search all agents
        for agent_dir in self.base_dir.glob("*/results"):
            for result_file in agent_dir.glob("*.json"):
                try:
                    with open(result_file, 'r') as f:
                        data = json.load(f)
                    
                    result = AgentResult(**data)
                    if result.reusable and result.reuse_count >= min_reuse_count:
                        results.append(result)
                except Exception:
                    continue
        
        return results
    
    def mark_reused(self, agent_id: str, result_id: str) -> bool:
        """Mark an agent result as reused.
        
        Args:
            agent_id: Agent identifier
            result_id: Result identifier
            
        Returns:
            True if marked, False if not found
        """
        result = self.get_result(agent_id, result_id)
        if not result:
            return False
        
        result.reuse_count += 1
        result.last_reused_at = AgentResult.now()
        
        self.store_result(result)
        return True
    
    def delete_result(self, agent_id: str, result_id: str) -> bool:
        """Delete an agent result.
        
        Args:
            agent_id: Agent identifier
            result_id: Result identifier
            
        Returns:
            True if deleted, False if not found
        """
        agent_dir = self._get_agent_dir(agent_id)
        result_file = agent_dir / f"{result_id}.json"
        
        if result_file.exists():
            result_file.unlink()
            return True
        
        return False
    
    def list_agent_results(self, agent_id: str) -> List[Dict]:
        """List all results for an agent.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            List of result summaries
        """
        agent_dir = self._get_agent_dir(agent_id)
        results = []
        
        for result_file in agent_dir.glob("*.json"):
            try:
                with open(result_file, 'r') as f:
                    data = json.load(f)
                
                results.append({
                    "id": data["id"],
                    "task_ref": data["task_ref"],
                    "conclusion": data["conclusion"][:100] + "..." if len(data["conclusion"]) > 100 else data["conclusion"],
                    "outcome": data["outcome"],
                    "reusable": data["reusable"],
                    "reuse_count": data["reuse_count"],
                    "completed_at": data["completed_at"]
                })
            except Exception:
                continue
        
        return results


# Singleton instance
_store = None

def get_store(base_dir: Optional[str] = None) -> AgentResultsStore:
    """Get or create the global agent results store."""
    global _store
    if _store is None:
        _store = AgentResultsStore(base_dir)
    return _store


def store_conclusion(
    agent_id: str,
    task_ref: str,
    conclusion: str,
    evidence: List[str],
    outcome: str = "success",
    duration_ms: int = 0,
    parent_task_ref: Optional[str] = None,
    task_description: str = "",
    reusable: bool = True
) -> str:
    """Convenience function to store an agent conclusion.
    
    Args:
        agent_id: Agent identifier
        task_ref: Task reference
        conclusion: Summary of findings
        evidence: List of evidence (file paths, outputs, etc.)
        outcome: success | partial | failure
        duration_ms: Duration in milliseconds
        parent_task_ref: Parent task reference (optional)
        task_description: What the agent was asked to do
        reusable: Whether this conclusion can be reused
        
    Returns:
        ID of stored result
    """
    store = get_store()
    
    result = AgentResult(
        id=AgentResult.create_id(agent_id, task_ref),
        agent_id=agent_id,
        task_ref=task_ref,
        parent_task_ref=parent_task_ref,
        task_description=task_description,
        conclusion=conclusion,
        evidence=evidence,
        outcome=outcome,
        duration_ms=duration_ms,
        started_at=AgentResult.now(),
        completed_at=AgentResult.now(),
        reusable=reusable,
        reuse_count=0,
        last_reused_at=None
    )
    
    return store.store_result(result)


def query_conclusions(task_ref: str) -> List[Dict]:
    """Query agent conclusions for a task.
    
    Args:
        task_ref: Task reference
        
    Returns:
        List of conclusion summaries
    """
    store = get_store()
    results = store.get_results_for_task(task_ref)
    
    return [
        {
            "agent_id": r.agent_id,
            "conclusion": r.conclusion,
            "outcome": r.outcome,
            "reusable": r.reusable,
            "reuse_count": r.reuse_count,
            "completed_at": r.completed_at
        }
        for r in results
    ]


# CLI entry point
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "list":
            agent_id = sys.argv[2] if len(sys.argv) > 2 else "vos-kernel"
            store = get_store()
            results = store.list_agent_results(agent_id)
            print(json.dumps(results, indent=2))
        
        elif command == "query":
            task_ref = sys.argv[2] if len(sys.argv) > 2 else ""
            results = query_conclusions(task_ref)
            print(json.dumps(results, indent=2))
        
        elif command == "reusable":
            store = get_store()
            results = store.get_reusable_conclusions()
            print(json.dumps([asdict(r) for r in results], indent=2))
        
        else:
            print(f"Unknown command: {command}")
            print("Available commands: list, query, reusable")
    
    else:
        print("Agent Results Store")
        print("Usage: agent_results.py <command> [args]")
        print("Commands:")
        print("  list [agent_id] - List results for an agent")
        print("  query <task_ref> - Query results for a task")
        print("  reusable - List reusable conclusions")
