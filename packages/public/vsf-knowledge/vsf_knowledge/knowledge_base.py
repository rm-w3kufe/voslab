"""
knowledge_base — Knowledge base del sistema VSF.

Proporciona acceso a la knowledge base del sistema.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any


class KnowledgeBase:
    """Knowledge base del sistema VSF."""
    
    def __init__(self, base_path: Optional[str] = None):
        """
        Inicializa la knowledge base.
        
        Args:
            base_path: Ruta base de la knowledge base (opcional)
        """
        if base_path:
            self.base_path = Path(base_path)
        else:
            # VOSLAB_PATH first (clone-safe), legacy ~/vOSlab last.
            _root = os.environ.get("VOSLAB_PATH", "")
            self.base_path = (Path(_root) / "knowledge" if _root
                              else Path.home() / "vOSlab" / "knowledge")
        
        self.cache: Dict[str, Any] = {}
    
    def load_knowledge(self, name: str) -> Optional[str]:
        """
        Loads a knowledge file.
        
        Args:
            name: file name (without extension)
            
        Returns:
            File contents or None if it does not exist
        """
        if name in self.cache:
            return self.cache[name]
        
        file_path = self.base_path / f"{name}.vsm"
        if file_path.exists():
            content = file_path.read_text()
            self.cache[name] = content
            return content
        
        return None
    
    def list_knowledge(self) -> List[str]:
        """
        Lists all knowledge files available.
        
        Returns:
            List of file names
        """
        if not self.base_path.exists():
            return []
        
        return [
            f.stem
            for f in self.base_path.glob("*.vsm")
            if f.is_file()
        ]
    
    def get_architecture(self) -> Optional[str]:
        """
        Gets the architecture file.
        
        Returns:
            Contents of the architecture file
        """
        return self.load_knowledge("architecture")
    
    def get_rsi_identity(self) -> Optional[str]:
        """
        Gets the RSI identity file.
        
        Returns:
            Contents of the RSI identity file
        """
        return self.load_knowledge("rsi_identity")
    
    def get_vsl_basics(self) -> Optional[str]:
        """
        Gets the VSL basics file.
        
        Returns:
            Contents of the VSL basics file
        """
        return self.load_knowledge("vsl_basics")
    
    def search(self, query: str) -> List[Dict[str, Any]]:
        """
        Busca en la knowledge base.
        
        Args:
            query: Texto a buscar
            
        Returns:
            Lista de resultados con nombre y contexto
        """
        results = []
        
        for name in self.list_knowledge():
            content = self.load_knowledge(name)
            if content and query.lower() in content.lower():
                # Find context around the match
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if query.lower() in line.lower():
                        context_start = max(0, i - 2)
                        context_end = min(len(lines), i + 3)
                        context = "\n".join(lines[context_start:context_end])
                        
                        results.append({
                            "name": name,
                            "line": i + 1,
                            "context": context,
                        })
                        break
        
        return results
