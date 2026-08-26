# Rightly OpenVINO E5 benchmark (post-submission)

This is an isolated, post-submission engineering benchmark. It does not
change Rightly's production runtime, installer, Vercel deployment, or the
existing model/cache in `AppData`. The benchmark reads the already-downloaded
E5-small snapshot and the existing real-corpus embedding cache.

## Machine and runtime

| Item | Observed value |
|---|---|
| OS | Windows 10 x64 (10.0.19045) |
| CPU | Intel Core i7-10510U, 4 physical / 8 logical cores |
| RAM | 15.8 GB |
| GPU | Intel UHD Graphics (iGPU); NVIDIA GeForce MX130 2 GB (dGPU) |
| NPU | Not detected |
| Python | 3.14.5 AMD64 |
| OpenVINO | 2026.3.0-22451 |
| OpenVINO devices seen | `CPU`, `GPU.0`, `GPU.1` |
| Device benchmarked | `CPU` only |
| CPU OpenVINO capabilities | FP32, INT8, BIN, EXPORT_IMPORT |
| OpenVINO settings | `INFERENCE_NUM_THREADS=4`, `PERFORMANCE_HINT=LATENCY` |
| PyTorch settings | intra-op `4`, inter-op `2` |

OpenVINO identified `GPU.0` as Intel UHD Graphics and `GPU.1` as the NVIDIA
adapter, but no GPU benchmark is included. No GPU/NPU performance claim is
made.

## Isolated install

The benchmark virtualenv contains only:

```text
numpy==2.5.2
openvino==2026.3.0
openvino-telemetry==2025.2.0
```

The download log reported a 75.8 MB OpenVINO wheel, a 12.6 MB NumPy wheel,
and a 25 KB telemetry wheel. Installed package footprints were approximately
223.57 MB for OpenVINO, 51.48 MB for NumPy, and 0.13 MB for telemetry. The
exporter uses the existing Rightly environment through `PYTHONPATH` for
SentenceTransformers/PyTorch; those packages were not copied into or changed
in the benchmark virtualenv.

## Model/export

- Model: `intfloat/multilingual-e5-small`.
- Source snapshot: existing local Hugging Face snapshot; offline-only flags
  were set (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`).
- Source `model.safetensors` SHA-256:
  `1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477`.
- Export: OpenVINO `convert_model` from the cached PyTorch BERT backbone,
  preserving masked mean pooling and L2 normalization.
- IR output: `e5_small_query_encoder.xml` (522,268 bytes) plus
  `e5_small_query_encoder.bin` (235,020,169 bytes).
- Embedding dimension: 384.
- Corpus cache checked read-only: 34,372 rows × 384 dimensions.

Reproduction from the benchmark worktree:

```powershell
$rightly = '<Rightly checkout>'
$env:PYTHONPATH="$rightly\.venv\Lib\site-packages"
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:OMP_NUM_THREADS='4'
$env:MKL_NUM_THREADS='4'
& .venv\Scripts\python.exe benchmarks\openvino_e5_benchmark.py `
  --model-dir '<HF_CACHE>\models--intfloat--multilingual-e5-small\snapshots\<snapshot>' `
  --cache '<Rightly checkout>\data\chunks\real_embeddings.npz' `
  --out-dir .benchmarks\e5 --threads 4 --runs 15
```

## Results

Three independent series were run. Each series used one warmup and 14 measured
one-query runs. The SentenceTransformers reference and OpenVINO timings both
include tokenization. The five queries are equivalence probes, not an accuracy
benchmark.

| Series | SentenceTransformers mean | OpenVINO mean | Speedup |
|---:|---:|---:|---:|
| 1 | 20.802 ms | 11.835 ms | 1.758× |
| 2 | 18.723 ms | 11.465 ms | 1.633× |
| 3 | 18.179 ms | 11.242 ms | 1.617× |
| All 42 measured runs | 19.235 ms | 11.514 ms | 1.671× pooled |

Across the three series, the speedup median was **1.633×** (range
**1.617–1.758×**). The pooled measured medians were 19.012 ms for the
SentenceTransformers reference and 11.704 ms for OpenVINO; pooled p95 values
were 23.083 ms and 13.674 ms respectively. These are approximate results for
this fixed workload and machine, not a product-wide or cross-device guarantee.

Equivalence checks passed:

- cosine similarity between reference and exported embeddings: min `1.0`,
  mean `1.0`, max `1.00000012`;
- top-10 corpus overlap: 100% for all five fixed queries;
- top-1 result matched for all five queries, including the first query:
  `nd45_2022::c071`.

The machine's pre-existing faster-whisper-small baseline was also measured
separately: CPU `int8`, 103.31-second WAV, 1 warmup + 2 measured runs,
27,616.7 ms mean (real-time factor 0.267). No OpenVINO ASR conversion was
attempted, so this report makes no ASR acceleration claim.

## Honest claim boundary

Allowed as post-submission evidence:

> On an Intel Core i7‑10510U test machine, an isolated OpenVINO CPU export of
> Rightly's existing E5-small query encoder produced numerically equivalent
> embeddings and measured approximately 1.62–1.76× lower end-to-end
> query-encoding latency than the local SentenceTransformers/PyTorch reference
> across three 15-run series (one warmup per series).

Not established by this benchmark:

- production integration or installer delivery;
- legal-answer accuracy improvement;
- performance on other machines;
- GPU, NPU, or NVIDIA acceleration;
- faster ASR/TTS/LLM;
- any claim that the submitted clip contained this later experiment.

The machine has no detected Intel NPU, and the production pipeline still uses
its existing SentenceTransformers CPU path. Any public description must label
this as a post-submission benchmark until an integration is separately tested
and reviewed.
