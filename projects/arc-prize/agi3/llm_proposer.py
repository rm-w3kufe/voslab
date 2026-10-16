# design: projects/arc-prize/arc_prize_design.vsm
"""
llm_proposer.py — S4: LLM como cerebro estratégico del sistema VSM-ARC-RSI.

Analiza puzzles unknown, propone hipótesis de patrón, y genera código
de estrategia candidata. Opera con Ollama local (offline) o cualquier
API compatible.

Uso:
    proposer = LLMProposer(model="qwen2.5-coder:1.5b")
    hypothesis = proposer.propose(puzzle, pattern_memory)
    print(hypothesis.text, hypothesis.code, hypothesis.confidence)
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# ── Types ────────────────────────────────────────────────────
Grid = np.ndarray
Trains = list


@dataclass
class Hypothesis:
    """Hipótesis de patrón generada por el LLM."""
    text: str                           # descripción textual del patrón
    code: str                           # código Python de la estrategia
    confidence: float                   # 0.0 - 1.0
    rationale: str                      # por qué este patrón
    similar_to: list = field(default_factory=list)  # patrones conocidos similares
    features_used: dict = field(default_factory=dict)  # features del puzzle
    timestamp: str = ""


@dataclass
class PuzzleFeatures:
    """Features extraídas de un puzzle para el LLM."""
    input_shapes: list
    output_shapes: list
    shape_change: str       # "same", "bigger", "smaller", "variable"
    input_colors: int
    output_colors: int
    color_change: str       # "same", "more", "less", "remap"
    input_objects: int
    output_objects: int
    object_change: str      # "same", "more", "less", "moved", "merged"
    symmetry: str           # "none", "horizontal", "vertical", "both", "rotational"
    size_ratio: float       # output_area / input_area


# ── Feature extraction ───────────────────────────────────────

def extract_features(trains: Trains) -> PuzzleFeatures:
    """Extraer features numéricas de un puzzle para el LLM."""
    if not trains:
        return PuzzleFeatures([], [], "unknown", 0, 0, "unknown",
                              0, 0, "unknown", "unknown", 1.0)

    in_shapes = []
    out_shapes = []
    in_colors = set()
    out_colors = set()
    in_objects_list = []
    out_objects_list = []

    for inp, out in trains:
        in_shapes.append(inp.shape)
        out_shapes.append(out.shape)
        in_colors.update(int(c) for c in np.unique(inp) if c != 0)
        out_colors.update(int(c) for c in np.unique(out) if c != 0)
        # Objects = connected components of non-zero cells
        in_objects_list.append(_count_objects(inp))
        out_objects_list.append(_count_objects(out))

    # Shape change
    if all(i == o for i, o in zip(in_shapes, out_shapes)):
        shape_change = "same"
    elif all(o[0] >= i[0] and o[1] >= i[1] for i, o in zip(in_shapes, out_shapes)):
        shape_change = "bigger"
    elif all(o[0] <= i[0] and o[1] <= i[1] for i, o in zip(in_shapes, out_shapes)):
        shape_change = "smaller"
    else:
        shape_change = "variable"

    # Color change
    ic, oc = len(in_colors), len(out_colors)
    if ic == oc:
        color_change = "same"
    elif oc > ic:
        color_change = "more"
    else:
        color_change = "less"

    # Object change
    avg_in_obj = sum(in_objects_list) / len(in_objects_list) if in_objects_list else 0
    avg_out_obj = sum(out_objects_list) / len(out_objects_list) if out_objects_list else 0
    if abs(avg_in_obj - avg_out_obj) < 0.5:
        object_change = "same"
    elif avg_out_obj > avg_in_obj:
        object_change = "more"
    else:
        object_change = "less"

    # Symmetry
    symmetry = _detect_output_symmetry(trains)

    # Size ratio
    total_in = sum(s[0] * s[1] for s in in_shapes)
    total_out = sum(s[0] * s[1] for s in out_shapes)
    size_ratio = total_out / total_in if total_in > 0 else 1.0

    return PuzzleFeatures(
        input_shapes=in_shapes,
        output_shapes=out_shapes,
        shape_change=shape_change,
        input_colors=ic,
        output_colors=oc,
        color_change=color_change,
        input_objects=int(avg_in_obj),
        output_objects=int(avg_out_obj),
        object_change=object_change,
        symmetry=symmetry,
        size_ratio=round(size_ratio, 2),
    )


def _count_objects(grid: Grid) -> int:
    """Contar objetos conectados (non-zero components)."""
    if grid.size == 0:
        return 0
    visited = np.zeros_like(grid, dtype=bool)
    count = 0
    for r in range(grid.shape[0]):
        for c in range(grid.shape[1]):
            if grid[r, c] != 0 and not visited[r, c]:
                _flood_fill(grid, visited, r, c)
                count += 1
    return count


def _flood_fill(grid, visited, r, c):
    """BFS flood fill."""
    rows, cols = grid.shape
    if r < 0 or r >= rows or c < 0 or c >= cols:
        return
    if visited[r, c] or grid[r, c] == 0:
        return
    visited[r, c] = True
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        _flood_fill(grid, visited, r + dr, c + dc)


def _detect_output_symmetry(trains: Trains) -> str:
    """Detectar simetría en outputs."""
    if not trains:
        return "none"

    _, out = trains[0]
    h, w = out.shape

    # Horizontal
    if h > 1 and np.array_equal(out, out[::-1, :]):
        return "horizontal"
    # Vertical
    if w > 1 and np.array_equal(out, out[:, ::-1]):
        return "vertical"
    # Both
    if h > 1 and w > 1 and np.array_equal(out, out[::-1, ::-1]):
        return "rotational"

    return "none"


def features_to_text(f: PuzzleFeatures) -> str:
    """Convertir features a texto legible para el LLM."""
    lines = [
        f"Input shapes: {f.input_shapes}",
        f"Output shapes: {f.output_shapes}",
        f"Shape change: {f.shape_change}",
        f"Input colors: {f.input_colors} (non-zero)",
        f"Output colors: {f.output_colors} (non-zero)",
        f"Color change: {f.color_change}",
        f"Avg input objects: {f.input_objects}",
        f"Avg output objects: {f.output_objects}",
        f"Object change: {f.object_change}",
        f"Output symmetry: {f.symmetry}",
        f"Size ratio (out/in): {f.size_ratio}",
    ]
    return "\n".join(lines)


def grid_to_text(grid: Grid, max_size: int = 20) -> str:
    """Convertir grid a texto compacto para el LLM."""
    if grid.size > max_size * max_size:
        # Downsample for display
        step = max(1, max(grid.shape) // max_size)
        grid = grid[::step, ::step]
    return "\n".join(" ".join(str(int(c)) for c in row) for row in grid)


# ── LLM Client ───────────────────────────────────────────────

class LLMProposer:
    """S4: LLM que analiza puzzles y propone hipótesis + código.

    Args:
        model: nombre del modelo Ollama
        url: URL del servidor Ollama
        temperature: temperatura de muestreo
        max_tokens: máximo tokens de respuesta
    """

    def __init__(self, model: str = "qwen2.5-coder:1.5b",
                 url: str = "http://localhost:11434",
                 temperature: float = 0.3,
                 max_tokens: int = 1024):
        self.model = model
        self.url = url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._available = None  # lazy check

    def is_available(self) -> bool:
        """Verificar si Ollama está corriendo con el modelo."""
        if self._available is not None:
            return self._available
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = [m.get("name", "") for m in data.get("models", [])]
                self._available = any(self.model in m for m in models)
                return self._available
        except Exception:
            self._available = False
            return False

    def propose(self, puzzle: dict, pattern_memory=None,
                max_retries: int = 2) -> Optional[Hypothesis]:
        """Analizar puzzle y generar hipótesis.

        Args:
            puzzle: dict con "train" y "test"
            pattern_memory: PatternMemory opcional para contexto
            max_retries: reintentos ante parsing errors

        Returns:
            Hypothesis o None si falla
        """
        if not self.is_available():
            return None

        trains = puzzle.get("train", [])
        features = extract_features(trains)

        # Build prompt
        prompt = self._build_prompt(puzzle, features, pattern_memory)

        # Call Ollama
        raw_response = self._call_ollama(prompt)
        if not raw_response:
            return None

        # Parse response
        for attempt in range(max_retries):
            hypothesis = self._parse_response(raw_response, features)
            if hypothesis is not None:
                return hypothesis
            # Retry with explicit format instruction
            prompt = prompt + "\n\nPlease respond in the exact format specified above."
            raw_response = self._call_ollama(prompt)

        return None

    def _build_prompt(self, puzzle: dict, features: PuzzleFeatures,
                      pattern_memory=None) -> str:
        """Construir prompt para el LLM."""
        trains = puzzle.get("train", [])

        # Known patterns summary
        known_section = ""
        if pattern_memory:
            active = pattern_memory.get_known_patterns(status="active")
            known_section = f"\nKnown patterns ({len(active)}): {', '.join(active[:20])}..."

        # Render puzzle
        puzzle_section = ""
        for i, (inp, out) in enumerate(trains):
            puzzle_section += f"\n--- Train pair {i} ---\n"
            puzzle_section += f"Input ({inp.shape[0]}x{inp.shape[1]}):\n"
            puzzle_section += grid_to_text(inp) + "\n"
            puzzle_section += f"Output ({out.shape[0]}x{out.shape[1]}):\n"
            puzzle_section += grid_to_text(out) + "\n"

        prompt = f"""You are an ARC puzzle pattern analyst. Analyze the following puzzle and identify the transformation rule.

FEATURES:
{features_to_text(features)}
{known_section}

PUZZLE:
{puzzle_section}

TASK:
1. Identify the transformation pattern (what changes from input to output)
2. Write a Python function `solve(trains, test)` that implements this pattern

The function signature must be:
    def solve(trains, test):
        # trains: list of (input_grid, output_grid) tuples (numpy arrays)
        # test: input grid (numpy array) to transform
        # Returns: output grid (numpy array) or None
        ...

RESPOND IN THIS EXACT FORMAT:
HYPOTHESIS: <one-line description of the pattern>
CONFIDENCE: <0.0 to 1.0>
RATIONALE: <why this pattern fits>
CODE:
```python
def solve(trains, test):
    ...
```
"""
        return prompt

    def _call_ollama(self, prompt: str) -> Optional[str]:
        """Llamar a Ollama API."""
        try:
            import urllib.request
            payload = json.dumps({
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            }).encode()

            req = urllib.request.Request(
                f"{self.url}/api/generate",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                return data.get("response", "")
        except Exception as e:
            print(f"  LLMProposer: Ollama error: {e}")
            return None

    def _parse_response(self, raw: str, features: PuzzleFeatures
                        ) -> Optional[Hypothesis]:
        """Parsear respuesta del LLM en Hypothesis."""
        try:
            # Extract HYPOTHESIS
            hyp_match = re.search(r"HYPOTHESIS:\s*(.+?)(?:\n|$)", raw)
            text = hyp_match.group(1).strip() if hyp_match else ""

            # Extract CONFIDENCE
            conf_match = re.search(r"CONFIDENCE:\s*([\d.]+)", raw)
            confidence = float(conf_match.group(1)) if conf_match else 0.5
            confidence = max(0.0, min(1.0, confidence))

            # Extract RATIONALE
            rat_match = re.search(r"RATIONALE:\s*(.+?)(?:\n|$)", raw)
            rationale = rat_match.group(1).strip() if rat_match else ""

            # Extract CODE
            code_match = re.search(r"```python\s*(.*?)```", raw, re.DOTALL)
            if not code_match:
                # Try without markdown
                code_match = re.search(r"def solve\(.*?\).*?(?=\n\n|\Z)", raw, re.DOTALL)
            code = code_match.group(1).strip() if code_match else ""

            if not code:
                return None

            return Hypothesis(
                text=text,
                code=code,
                confidence=confidence,
                rationale=rationale,
                features_used={
                    "shape_change": features.shape_change,
                    "color_change": features.color_change,
                    "object_change": features.object_change,
                    "symmetry": features.symmetry,
                    "size_ratio": features.size_ratio,
                },
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
        except Exception:
            return None
