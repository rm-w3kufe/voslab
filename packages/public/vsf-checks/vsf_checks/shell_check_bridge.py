"""
shell_check_bridge — Bridge to run the parent shell checks.

Provides a unified interface to run shell checks.
"""

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class ShellCheckBridge:
    """Bridge to run the parent shell checks."""
    
    def __init__(self, checks_dir: str):
        """
        Initializes the bridge.
        
        Args:
            checks_dir: directory holding the shell checks
        """
        self.checks_dir = Path(checks_dir)
        self.manifest = self._load_manifest()
    
    def _load_manifest(self) -> Dict:
        """Loads the check manifest."""
        manifest_path = self.checks_dir.parent / "vsf_checks" / "checks_manifest.json"
        if manifest_path.exists():
            import json
            with open(manifest_path, 'r') as f:
                return json.load(f)
        return {"checks": []}
    
    def list_checks(self) -> List[str]:
        """
        Lists all checks available.
        
        Returns:
            List of check names
        """
        if not self.checks_dir.exists():
            return []
        
        return [
            f.name
            for f in self.checks_dir.iterdir()
            if f.is_file() and os.access(f, os.X_OK)
        ]
    
    def run_check(self, check_name: str) -> Tuple[bool, str]:
        """
        Runs a specific check.
        
        Args:
            check_name: name of the check
            
        Returns:
            Tuple of (success, output)
        """
        check_path = self.checks_dir / check_name
        
        if not check_path.exists():
            return False, f"Check no encontrado: {check_name}"
        
        if not os.access(check_path, os.X_OK):
            return False, f"Check no es ejecutable: {check_name}"
        
        try:
            result = subprocess.run(
                [str(check_path)],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Check timeout (30s)"
        except Exception as e:
            return False, f"Error ejecutando check: {e}"
    
    def run_all_checks(self) -> Dict[str, Tuple[bool, str]]:
        """
        Runs all checks available.
        
        Returns:
            Dict of results {check_name: (success, output)}
        """
        results = {}
        
        for check_name in self.list_checks():
            success, output = self.run_check(check_name)
            results[check_name] = (success, output)
        
        return results
    
    def get_check_categories(self) -> Dict[str, List[str]]:
        """
        Gets checks grouped by category.
        
        Returns:
            Dict {category: [checks]}
        """
        categories = {}
        
        for check_name in self.list_checks():
            # Extract category from filename (e.g., "boot-load-test" -> "boot")
            if "-" in check_name:
                category = check_name.split("-")[0]
            else:
                category = "other"
            
            if category not in categories:
                categories[category] = []
            categories[category].append(check_name)
        
        return categories
    
    def run_checks_by_category(self, category: str) -> Dict[str, Tuple[bool, str]]:
        """
        Runs all checks of a specific category.
        
        Args:
            category: category to run
            
        Returns:
            Dict of results
        """
        results = {}
        categories = self.get_check_categories()
        
        if category not in categories:
            return {"error": (False, f"Categoría no encontrada: {category}")}
        
        for check_name in categories[category]:
            success, output = self.run_check(check_name)
            results[check_name] = (success, output)
        
        return results
    
    def get_check_info(self, check_name: str) -> Dict:
        """
        Gets detailed information about a check.
        
        Args:
            check_name: name of the check
            
        Returns:
            Dict with the check's information
        """
        check_path = self.checks_dir / check_name
        
        if not check_path.exists():
            return {"error": f"Check no encontrado: {check_name}"}
        
        # Find in manifest
        for check in self.manifest.get("checks", []):
            if check["name"] == check_name:
                return check
        
        # Return basic info if not in manifest
        return {
            "name": check_name,
            "category": check_name.split("-")[0] if "-" in check_name else "other",
            "path": str(check_path),
            "size": check_path.stat().st_size,
            "description": f"Check: {check_name}"
        }
