# design: projects/arc-prize/arc_prize_design.vsm
"""
strategy_sandbox.py — Sandbox para ejecutar código generado por LLM.

Ejecuta código Python de forma aislada con:
  - Timeout configurable
  - Output shape validation
  - Sin acceso a archivos/red/sistema
  - Restricted builtins (sin __import__, eval, exec)

Uso:
    sandbox = StrategySandbox(timeout_s=30)
    result = sandbox.execute(code_str, trains, test_input)
"""

import ast
import signal
import sys
import traceback
from typing import Optional, Tuple

import numpy as np

# ── Types ────────────────────────────────────────────────────
Grid = np.ndarray
Trains = list


class SandboxError(Exception):
    """Error en la ejecución del sandbox."""
    pass


class TimeoutError(SandboxError):
    """Timeout en la ejecución."""
    pass


class SecurityError(SandboxError):
    """Intento de acceso no permitido."""
    pass


class ValidationError(SandboxError):
    """Output no cumple formato esperado."""
    pass


# ── Safe builtins ────────────────────────────────────────────

_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool,
    "dict": dict, "dir": dir, "divmod": divmod,
    "enumerate": enumerate, "filter": filter, "float": float,
    "format": format, "frozenset": frozenset,
    "getattr": getattr, "globals": globals, "hasattr": hasattr,
    "hash": hash, "hex": hex, "id": id, "int": int,
    "isinstance": isinstance, "issubclass": issubclass,
    "iter": iter, "len": len, "list": list, "map": map,
    "max": max, "min": min, "next": next,
    "oct": oct, "ord": ord, "pow": pow,
    "print": print, "property": property,
    "range": range, "repr": repr, "reversed": reversed,
    "round": round, "set": set, "setattr": setattr,
    "slice": slice, "sorted": sorted, "str": str,
    "sum": sum, "super": super, "tuple": tuple,
    "type": type, "zip": zip,
    # numpy is allowed
    "np": np, "numpy": np,
}

# Allowed modules for import
_ALLOWED_MODULES = {"numpy", "math", "collections", "itertools", "functools", "time"}


def _safe_import(name, *args, **kwargs):
    """Restricted import: only allow specific modules.

    Python's __import__ has a complex signature: __import__(name, globals=None, locals=None, fromlist=(), level=0)
    We only care about the name and fromlist.
    """
    mod = name.split(".")[0]
    if mod not in _ALLOWED_MODULES:
        raise ImportError(f"Import not allowed: {name}")
    import importlib
    return importlib.import_module(name)


# Add __import__ to safe builtins
_SAFE_BUILTINS["__import__"] = _safe_import


# ── AST validation ───────────────────────────────────────────

FORBIDDEN_NODES = (
    ast.Global, ast.Nonlocal,         # no global/nonlocal
    ast.Delete,                       # no delete
)

FORBIDDEN_IMPORTS = {
    "os", "sys", "subprocess", "shutil", "pathlib",
    "socket", "http", "urllib", "requests",
    "builtins", "importlib",
}

FORBIDDEN_NAMES = {
    "__builtins__", "__loader__", "__spec__",
    "exec", "eval", "compile", "open", "input",
}


def _validate_code(code_str: str):
    """Validar que el código no contiene operaciones peligrosas."""
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        raise SecurityError(f"Syntax error in generated code: {e}")

    for node in ast.walk(tree):
        # Check forbidden node types
        if isinstance(node, FORBIDDEN_NODES):
            raise SecurityError(f"Forbidden AST node: {type(node).__name__}")

        # Check forbidden imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod in FORBIDDEN_IMPORTS:
                    raise SecurityError(f"Forbidden import: {alias.name}")

        if isinstance(node, ast.ImportFrom):
            if node.module:
                mod = node.module.split(".")[0]
                if mod in FORBIDDEN_IMPORTS:
                    raise SecurityError(f"Forbidden import: {node.module}")

        # Check forbidden names
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise SecurityError(f"Forbidden name: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            raise SecurityError(f"Forbidden attribute: {node.attr}")


# ── Sandbox ──────────────────────────────────────────────────

class StrategySandbox:
    """Ejecuta código generado de forma segura.

    Args:
        timeout_s: máximo segundos de ejecución
        max_output_size: máximo tamaño del grid de salida (filas × cols)
    """

    def __init__(self, timeout_s: int = 30, max_output_size: int = 10000):
        self.timeout_s = timeout_s
        self.max_output_size = max_output_size

    def execute(self, code_str: str, trains: Trains, test_input: Grid
                ) -> Tuple[Optional[Grid], str]:
        """Ejecutar código generado contra un puzzle.

        El código debe definir una función: `def solve(trains, test) -> Grid`

        Args:
            code_str: código Python con la función solve()
            trains: lista de (input_grid, output_grid)
            test_input: grid de test input

        Returns:
            (result_grid, signal_string)
            signal: "ok" | "timeout" | "security_error" | "crash" | "invalid_output"
        """
        # 1. Validate code safety
        try:
            _validate_code(code_str)
        except SecurityError as e:
            return None, f"security_error:{e}"

        # 2. Compile
        try:
            compiled = compile(code_str, "<llm_generated>", "exec")
        except SyntaxError as e:
            return None, f"compile_error:{e}"

        # 3. Execute with restricted globals
        namespace = {"__builtins__": _SAFE_BUILTINS.copy()}
        try:
            exec(compiled, namespace)
        except Exception as e:
            return None, f"exec_error:{e}"

        # 4. Check that solve() exists
        solve_fn = namespace.get("solve")
        if not callable(solve_fn):
            return None, "no_solve_function"

        # 5. Execute solve with timeout
        try:
            result = self._run_with_timeout(solve_fn, trains, test_input)
        except TimeoutError:
            return None, f"timeout:{self.timeout_s}s"
        except Exception as e:
            return None, f"crash:{type(e).__name__}:{e}"

        # 6. Validate output
        if result is None:
            return None, "returned_none"

        if not isinstance(result, np.ndarray):
            return None, f"wrong_type:{type(result).__name__}"

        if result.ndim != 2:
            return None, f"wrong_dims:{result.ndim}"

        if result.size > self.max_output_size:
            return None, f"too_large:{result.shape}"

        if not np.issubdtype(result.dtype, np.integer):
            # Try to convert
            try:
                result = result.astype(np.int32)
            except (ValueError, TypeError):
                return None, f"non_integer_dtype:{result.dtype}"

        return result, "ok"

    def _run_with_timeout(self, fn, *args):
        """Ejecutar función con timeout (Unix signal)."""
        def handler(signum, frame):
            raise TimeoutError(f"Execution timed out after {self.timeout_s}s")

        old_handler = signal.signal(signal.SIGALRM, handler)
        signal.alarm(self.timeout_s)
        try:
            result = fn(*args)
            return result
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    def validate_output(self, result: Grid, expected_shape: Optional[tuple] = None
                        ) -> Tuple[bool, str]:
        """Validar que el output tiene el shape correcto."""
        if result is None:
            return False, "None"
        if not isinstance(result, np.ndarray):
            return False, f"not ndarray: {type(result)}"
        if result.ndim != 2:
            return False, f"wrong ndim: {result.ndim}"
        if expected_shape and result.shape != expected_shape:
            return False, f"shape mismatch: {result.shape} != {expected_shape}"
        return True, "ok"
