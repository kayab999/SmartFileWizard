# FileWizard — Performance baseline (P1-4 / A4)

**Date:** 2026-11-11 · **Version:** 0.11.1+ · **Machine:** dev workstation
(Linux, Python 3.11). Numbers are reproducible with the commands below; absolute
values will vary by hardware, the *ratios* are the useful signal.

## Commands

```bash
# Metadata-only throughput on a real directory
filewizard benchmark --source ~/Downloads --iterations 3 --limit 100

# Full plan pipeline (scan → facts → match → plan) with N concurrent
# fact collectors (A2):
filewizard run --source ~/Downloads --preset images-cascade --workers 4
```

## Results

### Metadata-only planning (no perception)

Corpus: 300 mixed files (txt/json/png). `plan_operations`, dry-run, no extractors.

| workers | files/s |
|---:|---:|
| 1 | ~3000 |
| 2–8 | ~1900–1950 |

Metadata planning is already fast (~3k files/s, stat + mime + hashing).
Thread overhead makes `workers > 1` a small net loss here — **keep the
default of 1 for perception-less runs.**

### Perception-bound planning (the case parallelism is for)

Corpus: 60 files, simulated HTTP perception round-trip of 120 ms per file
(this is what OCR/VLM stage-2/3 looks like in practice — I/O-bound wait).

| workers | files/s | speedup |
|---:|---:|---:|
| 1 | 8.3 | 1.0× |
| 2 | 16.5 | 2.0× |
| 4 | 32.9 | 4.0× |
| 8 | 61.6 | 7.4× |

Near-linear scaling for I/O-bound extractors: results are consumed strictly
in scan order, so planning stays deterministic while the wall-clock cost of
HTTP round-trips overlaps.

Notes:
- CPU-bound pure-Python extractors do **not** scale (GIL); the win is for
  I/O waits (HTTP providers) and native code that releases the GIL (torch).
- The perception HTTP layer's 1-inflight lock (0.9) serializes calls to the
  *same* endpoint; use distinct providers/ports to overlap real calls.

## Batched stage-1 inference (A1)

`ZeroShotClassifier.predict_batch` evaluates several images per forward
pass (`cascade.stage1_batch_size` ≥ 2). Per-image scores are identical to
the single-image path by construction (same softmax over the same label
set); the gain is throughput on the vision tower. `Stage1BatchQueue`
buffers per-file requests and flushes in model-sized batches.

## Guidelines

- Perception-less directories: leave `--workers 1`.
- Cascade with HTTP OCR/VLM enabled: `--workers 2..4` typically 2–4× faster;
  beyond ~8 the provider (llama.cpp server) usually becomes the bottleneck.
- `stage1_batch_size`: 4–8 on CPU, 16–32 on GPU.
