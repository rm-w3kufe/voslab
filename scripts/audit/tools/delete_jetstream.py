#!/usr/bin/env python3
"""Delete empty JetStream streams: VSF_SEMANTIC, VSF_TELEMETRY."""

import asyncio
import json
import sys
import nats

async def main():
    nc = await nats.connect("nats://localhost:4222")

    # List streams first
    resp = await nc.request("$JS.API.STREAM.LIST", json.dumps({"offset": 0}).encode(), timeout=5)
    print("STREAM LIST:", resp.data.decode())

    # Delete the two empty streams
    for name in ["VSF_SEMANTIC", "VSF_TELEMETRY"]:
        try:
            resp = await nc.request(f"$JS.API.STREAM.DELETE.{name}", b"", timeout=5)
            result = json.loads(resp.data.decode())
            if result.get("success", False):
                print(f"✓ Deleted stream: {name}")
            else:
                print(f"✗ Delete failed for {name}: {result}")
        except nats.errors.NoRespondersError:
            print(f"ℹ No responder for {name} — not found or already deleted")
        except Exception as e:
            print(f"✗ Error deleting {name}: {e}")

    # Re-list
    resp = await nc.request("$JS.API.STREAM.LIST", json.dumps({"offset": 0}).encode(), timeout=5)
    print("STREAM LIST after delete:", resp.data.decode())

    await nc.close()

if __name__ == "__main__":
    asyncio.run(main())
