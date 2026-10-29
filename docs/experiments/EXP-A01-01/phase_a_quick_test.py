#!/usr/bin/env python3
"""Quick evaluation: 5 streams only."""
import json
import time
from pathlib import Path
from anyjev import Decider, Question
from anyjev.backends.llamacpp import LlamaCppBackend

CORPUS_DIR = Path("/opt/corpus")
GROUND_TRUTH = CORPUS_DIR / "ground_truth.json"

print("Loading model...")
start = time.time()
backend = LlamaCppBackend(
    "/opt/Spark-X2.5-1.7B-Q4_K_M.gguf",
    n_ctx=2048,
    n_threads=4,
    verbose=False
)
decider = Decider(backend)
print(f"Model loaded in {time.time()-start:.1f}s")

with open(GROUND_TRUTH) as f:
    ground_truth = json.load(f)

# Evaluate only 5 streams
test_streams = list(ground_truth["streams"].items())[:5]
print(f"\nEvaluating {len(test_streams)} streams...")

for stream_id, expected in test_streams:
    stream_file = CORPUS_DIR / f"{stream_id}.jsonl"
    if not stream_file.exists():
        print(f"  SKIP {stream_id} (not found)")
        continue
    
    with open(stream_file) as f:
        events = [json.loads(line) for line in f][:10]
    state = "\n".join([json.dumps(e) for e in events])
    
    question = Question.choice(
        "Is this a violation?",
        ["A0_violation", "A01_violation", "clean"],
        name="classification"
    )
    
    start = time.time()
    result = decider.decide(state, [question])
    latency = time.time() - start
    
    predicted = result["classification"].answer
    confidence = result["classification"].confidence
    status = "✓" if predicted == expected else "✗"
    
    print(f"  {status} {stream_id:15s} | exp={expected:12s} | pred={predicted:12s} | conf={confidence:.3f} | {latency:.1f}s")

print("\nDone!")
