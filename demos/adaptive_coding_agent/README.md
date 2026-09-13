# Adaptive Coding Agent Demo

This demo is an external consumer of the local `harness` package. Install the
harness first, then install this demo:

```bash
pip install -e ../../harness
pip install -e .
```

The two-step install avoids a relative direct-reference dependency in
`pyproject.toml`; pip requires absolute `file://` URLs for that form, which
would make this demo depend on the checkout path.
