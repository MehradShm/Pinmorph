# Local Lens runtime

OpenAI CLIP image inference and a small zero-shot upload policy run in a separate CPU service.
The API and RQ workers call it over the private Compose network. Host port 8090 binds only
to loopback. No model downloads occur at startup or during a request.

`make lens-prepare` explicitly downloads and verifies `data/models/ViT-B-32.pt`.
`make up` prepares it and starts all services. The weight directory is ignored by Git and
mounted read-only. `make lens-backfill` indexes an existing catalog; new uploads index in
the media worker. `make lens-evaluate` records exact/HNSW agreement and latency.

Vendored `model.py`, `simple_tokenizer.py` and BPE vocabulary come from
https://github.com/openai/CLIP at commit d05afc436d78f1c48dc0dbf8e5980a9d471f35f6.
Their original MIT license is in `vendor/LICENSE`. The encoder uses the original evaluation
transform from `clip/clip.py`, rebuilding the model from the verified JIT archive's state
and running float32 CPU inference. Application version: `embedder:clip-image-crop:v1`.

The classifier policy `safety:clip-zero-shot:v1` is deliberately a learning baseline, with
explicit prompts and hold thresholds in `server.py`. A cosine similarity is not a calibrated
risk probability. Replace/evaluate the classifier before any real safety deployment.
