"""Measure the feasibility numbers the submission has to disclose:
index build time, resident memory, and per-turn latency.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def rss_mb() -> float:
    try:
        import ctypes
        import ctypes.wintypes as wt

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return counters.WorkingSetSize / 1e6
    except Exception:  # noqa: BLE001
        return float("nan")


def main() -> None:
    from evaluator.local_evaluator import (
        MAX_TURNS, TOP_K, catalog_index, coarse_category, customer_reply,
        initial_message, materialize_hidden_fields, normalize_recommendations,
    )
    from starter.agent import Agent

    catalog = str(ROOT / "data" / "catalog.jsonl")
    before = rss_mb()
    started = time.perf_counter()
    agent = Agent(catalog)
    build = time.perf_counter() - started
    print(f"index build : {build:.1f}s")
    print(f"memory      : {rss_mb():.0f} MB resident (delta {rss_mb()-before:.0f} MB)")

    catalog_ids, categories, products = catalog_index(catalog)
    samples = [json.loads(l) for l in (ROOT / "data" / "public_set.jsonl").open(encoding="utf-8") if l.strip()][:60]

    latencies = []
    for sample in samples:
        sid = sample["sample_id"]
        agent.reset(sid, sample["user_profile"])
        target = str(sample["ground_truth"]["parent_asin"])
        card, behavior = materialize_hidden_fields(sample, products)
        eff = {**sample, "intent_card": card, "behavior": behavior}
        disclosed, boundary_used = set(), False
        applied = sample["scenario_type"] != "intent_override"
        message = initial_message(eff, coarse_category(categories.get(target, [])), disclosed)
        for turn in range(1, MAX_TURNS + 1):
            t0 = time.perf_counter()
            response = agent.respond(sid, message, turn, TOP_K)
            latencies.append((time.perf_counter() - t0) * 1000)
            ranked = normalize_recommendations(response.get("recommendations"), catalog_ids)
            if applied and target in ranked:
                break
            if turn == MAX_TURNS:
                break
            override = behavior.get("override") or {}
            if not applied and turn + 1 == int(override.get("turn", 3)):
                applied = True
                disclosed.add(str(override.get("new_value", "")))
                message = str(override.get("message", ""))
            else:
                message, boundary_used = customer_reply(eff, response.get("ask_attribute"), disclosed, boundary_used)

    latencies.sort()
    print(f"turns timed : {len(latencies)}")
    print(f"latency     : mean={statistics.fmean(latencies):.1f}ms "
          f"p50={latencies[len(latencies)//2]:.1f}ms "
          f"p95={latencies[int(len(latencies)*0.95)]:.1f}ms "
          f"max={latencies[-1]:.1f}ms")
    print("tokens      : 0 (no model calls, stdlib only)")


if __name__ == "__main__":
    main()
