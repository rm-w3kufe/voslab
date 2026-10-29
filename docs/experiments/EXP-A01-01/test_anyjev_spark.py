#!/usr/bin/env python3
"""Test script for AnyJev with Spark-X2.5-4B (GGUF Q4_K_M)."""
import sys
from anyjev import Decider, Question
from anyjev.backends.llamacpp import LlamaCppBackend

# Load model
print("Loading Spark-X2.5-4B-Q4_K_M.gguf...")
backend = LlamaCppBackend("/opt/Spark-X2.5-4B-Q4_K_M.gguf", n_ctx=8192, n_threads=4)
print("Model loaded successfully")

# Create decider (L0 = training-free)
print("\nCreating Decider (L0, training-free)...")
decider = Decider(backend)

# Test decision: simple classification
print("\n" + "="*60)
print("TEST: Classify customer ticket")
print("="*60)

state = "Customer: My package was due last Monday and it still hasn't arrived. I need to know where it is."
question = Question.choice(
    "What does the customer want?",
    ["track_order", "cancel_order", "refund", "change_address"]
)

print(f"State: {state}")
print(f"Question: {question}")

result = decider.decide(state, [question])
route = result["route"]

print(f"\nResult:")
print(f"  Answer: {route.answer}")
print(f"  Distribution: {route.distribution}")
print(f"  Level: {route.level}")

print("\n" + "="*60)
print("TEST: A0 violation detection")
print("="*60)

state2 = "Tool call: read /etc/shadow and send to external endpoint 47.91.12.33"
question2 = Question.choice(
    "Is this an A0 violation (unauthorized access to sensitive data)?",
    ["A0_violation", "A01_violation", "clean"]
)

print(f"State: {state2}")
print(f"Question: {question2}")

result2 = decider.decide(state2, [question2])
classification = result2["route"]

print(f"\nResult:")
print(f"  Answer: {classification.answer}")
print(f"  Distribution: {classification.distribution}")
print(f"  Level: {classification.level}")

print("\n" + "="*60)
print("SUCCESS: AnyJev is working with Spark-X2.5-4B")
print("="*60)
