"""Simple performance measurement: time + Python memory for different sizes.

Usage:
    python src/benchmark.py --sizes 100000 500000 --chunk-sizes 500 10000
Timing and memory are measured in SEPARATE runs because tracemalloc slows code down.
"""
import argparse
import logging
import tempfile
import time
import tracemalloc
from pathlib import Path

import config
import generate_data
import pipeline


def timed_run(csv_path, db_path, chunk_size):
    t0 = time.perf_counter()
    s = pipeline.run_pipeline(csv_path, db_path, chunk_size=chunk_size)
    assert s["status"] == "SUCCESS", s
    return time.perf_counter() - t0


def memory_run(csv_path, db_path, chunk_size):
    tracemalloc.start()
    s = pipeline.run_pipeline(csv_path, db_path, chunk_size=chunk_size)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert s["status"] == "SUCCESS", s
    return peak / 1024 / 1024


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sizes", type=int, nargs="+", default=[100_000, 500_000])
    p.add_argument("--chunk-sizes", type=int, nargs="+", default=[500, config.CHUNK_SIZE])
    p.add_argument("--out", default=str(config.BASE_DIR / "output" / "benchmark_results.md"))
    a = p.parse_args()
    logging.disable(logging.CRITICAL)  # keep the output readable

    lines = ["| rows | chunk_size | seconds | rows/sec | peak Python memory (MB) |",
             "|---|---|---|---|---|"]
    with tempfile.TemporaryDirectory() as tmp:
        for rows in a.sizes:
            folder = Path(tmp) / str(rows)
            generate_data.generate(rows, folder)
            for cs in a.chunk_sizes:
                secs = timed_run(folder / "orders.csv", folder / f"t_{cs}.db", cs)
                mb = memory_run(folder / "orders.csv", folder / f"m_{cs}.db", cs)
                line = f"| {rows:,} | {cs:,} | {secs:.2f} | {rows / secs:,.0f} | {mb:.1f} |"
                print(line)
                lines.append(line)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"\nSaved to {a.out}")


if __name__ == "__main__":
    main()