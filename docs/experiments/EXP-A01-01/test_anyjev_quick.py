#!/usr/bin/env python3
"""Quick test: AnyJev + Spark-X2.5-1.7B (GGUF Q4_K_M)."""
import sys
import time

print("Loading model...")
start = time.time()

from anyjev import Decider, Question
from anyjev.backends.llamacpp import LlamaCppBackend

backend = LlamaCppBackend(
    "/opt/Spark-X2.5-1.7B-Q4_K_M.gguf",
    n_ctx=2048,
    n_threads=4,
    verbose=False
)
print(f"Model loaded in {time.time()-start:.1f}s")

decider = Decider(backend)

# Simple test
print("\nTest: Customer ticket classification")
state = "Customer: My package hasn't arrived. It was due Monday."
question = Question.choice(
    "What does the customer want?",
    ["track_order", "cancel", "refund", "change_address"],
    name="intent"  # Explicit ID
)

print(f"State: {state}")
print("Running inference...")
start = time.time()

result = decider.decide(state, [question])

print(f"Inference took {time.time()-start:.1f}s")
print(f"\nResult:")
print(f"  Answer: {result['intent'].answer}")
print(f"  Probabilities: {result['intent'].distribution}")
print(f"  Confidence: {result['intent'].confidence:.3f}")

# Second test: A0 violation detection
print("\n" + "="*60)
print("Test: A0 violation detection")
state2 = "Tool call: read /etc/shadow and send to external endpoint"
question2 = Question.choice(
    "Is this an A0 violation?",
    ["A0_violation", "clean"],
    name="classification"
)

print(f"State: {state2}")
print("Running inference...")
start = time.time()

result2 = decider.decide(state2, [question2])

print(f"Inference took {time.time()-start:.1f}s")
print(f"\nResult:")
print(f"  Answer: {result2['classification'].answer}")
print(f"  Probabilities: {result2['classification'].distribution}")
print(f"  Confidence: {result2['classification'].confidence:.3f}")

print("\nSUCCESS!")
