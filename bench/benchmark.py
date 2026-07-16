"""kenze benchmark: the never-OOM claim, measured.

Generates a big synthetic CSV, then runs the same aggregation task with pandas,
polars and kenze - each given the same memory budget - and reports outcome,
wall time and peak memory. pandas (eager) blows past the budget and dies;
kenze streams within it (spilling to disk) and finishes.

    python bench/benchmark.py --rows 40000000 --mem-gb 2
    python bench/benchmark.py --rows 500000 --engines kenze --mem-gb 0   # quick local

Results are printed as a markdown table and written to bench/RESULTS.md (and to
the GitHub Actions job summary when run in CI).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CATS = [f"cat_{i:02d}" for i in range(30)]
_CHUNK = 100_000


def generate(path: str, rows: int, seed: int = 0) -> float:
    """Stream a synthetic CSV to disk (generation itself never holds it in RAM).
    Columns: id, category (30 values), value [0,1), value2 [0,1000), flag."""
    import random
    rnd = random.Random(seed)
    t0 = time.time()
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("id,category,value,value2,flag\n")
        buf = []
        for i in range(rows):
            buf.append(f"{i},{CATS[i % 30]},{rnd.random():.6f},{rnd.random() * 1000:.4f},{i & 1}\n")
            if len(buf) >= _CHUNK:
                f.writelines(buf)
                buf = []
        if buf:
            f.writelines(buf)
    return time.time() - t0


def _peak_rss(pid: int, stop: threading.Event, out: list) -> None:
    try:
        import psutil
        p = psutil.Process(pid)
        peak = 0
        while not stop.is_set():
            try:
                rss = p.memory_info().rss
                for ch in p.children(recursive=True):
                    try:
                        rss += ch.memory_info().rss
                    except Exception:
                        pass
                peak = max(peak, rss)
            except Exception:
                break
            time.sleep(0.05)
        out.append(peak)
    except Exception:
        out.append(0)


def run_engine(engine: str, inp: str, mem_gb: float, timeout: int = 3600) -> dict:
    out_file = os.path.join(HERE, f"_out_{engine}.csv")
    cmd = [sys.executable, os.path.join(HERE, "_engine.py"),
           "--engine", engine, "--input", inp, "--output", out_file,
           "--mem-gb", str(mem_gb)]
    stop = threading.Event()
    peak: list = []
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    th = threading.Thread(target=_peak_rss, args=(proc.pid, stop, peak), daemon=True)
    th.start()
    try:
        out, _ = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        out, rc = "timeout", -1
    stop.set()
    th.join(timeout=1)
    secs = time.time() - t0

    text = out or ""
    if rc == 0:
        outcome = "ok"
    elif rc in (137, -9, 139, -11) or "MemoryError" in text or "bad_alloc" in text:
        outcome = "OOM"
    elif "ModuleNotFoundError" in text or "No module named" in text:
        outcome = "not installed"
    else:
        outcome = "error"
    for junk in (out_file,):
        try:
            os.remove(junk)
        except OSError:
            pass
    return {"engine": engine, "outcome": outcome, "secs": secs,
            "peak": peak[0] if peak else 0, "log": text.strip()}


def _fmt_bytes(b: int) -> str:
    if not b:
        return "-"
    g = b / (1024 ** 3)
    return f"{g:.2f} GB" if g >= 1 else f"{b / (1024 ** 2):.0f} MB"


def _table(rows: int, mem_gb: float, file_gb: float, results: list) -> str:
    label = {"ok": "finished", "OOM": "**OOM (crashed)**",
             "error": "error", "not installed": "not installed", "timeout": "timeout"}
    lines = [
        f"**Task:** read {rows:,}-row CSV ({file_gb:.1f} GB) -> filter -> group by "
        f"category -> sum/avg/count, at a **{mem_gb:g} GB** memory budget.",
        "",
        "| engine | outcome | wall time | peak memory |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        secs = f"{r['secs']:.1f}s" if r["outcome"] in ("ok",) else "-"
        lines.append(f"| {r['engine']} | {label.get(r['outcome'], r['outcome'])} "
                     f"| {secs} | {_fmt_bytes(r['peak'])} |")
    lines += [
        "",
        "_pandas (eager) and polars are hard-capped to the budget with RLIMIT_AS "
        "(they have no built-in spill). kenze gets the same budget via its own "
        "`--memory-limit` and spills the overflow to disk - that self-limiting is "
        "the feature._",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=40_000_000)
    ap.add_argument("--mem-gb", type=float, default=2.0,
                    help="memory budget per engine (0 = no cap; for quick local runs)")
    ap.add_argument("--engines", default="pandas,polars,kenze")
    ap.add_argument("--data", default=os.path.join(HERE, "_bench_data.csv"))
    ap.add_argument("--keep", action="store_true", help="keep the generated data file")
    a = ap.parse_args()

    engines = [e.strip() for e in a.engines.split(",") if e.strip()]
    print(f"generating {a.rows:,} rows -> {a.data} ...", flush=True)
    gen_s = generate(a.data, a.rows)
    file_gb = os.path.getsize(a.data) / (1024 ** 3)
    print(f"  {file_gb:.2f} GB written in {gen_s:.1f}s\n", flush=True)

    results = []
    for e in engines:
        print(f"running {e} (budget {a.mem_gb:g} GB) ...", flush=True)
        r = run_engine(e, a.data, a.mem_gb)
        print(f"  {e}: {r['outcome']}  {r['secs']:.1f}s  peak {_fmt_bytes(r['peak'])}", flush=True)
        if r["outcome"] == "error" and r["log"]:
            print("  " + r["log"].replace("\n", "\n  "), flush=True)
        results.append(r)

    table = _table(a.rows, a.mem_gb, file_gb, results)
    print("\n" + table + "\n")
    with open(os.path.join(HERE, "RESULTS.md"), "w", encoding="utf-8") as f:
        f.write("# kenze benchmark results\n\n" + table + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## kenze benchmark\n\n" + table + "\n")

    if not a.keep:
        try:
            os.remove(a.data)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
