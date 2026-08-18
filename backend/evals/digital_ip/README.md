# Digital IP fixture contract eval

Run from `backend/`:

```bash
python -m evals.digital_ip.runner --check
```

This provider-free track verifies five deterministic projection contracts: positioning, tone,
prohibited language, safety, and visual guidance. Its checked JSON/Markdown artifacts describe
fixture contract conformance only. They do not measure live embeddings, retrieval quality, model
accuracy, or production effectiveness.
