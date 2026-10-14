# vico-agent

The local Python sidecar that the Vico desktop app starts. It binds only to `127.0.0.1`, requires the per-launch token in `VICO_TOKEN` on every request, and owns the agent, tools, providers, audio capture, settings and history.

```bash
uv sync
uv run python -m app.main
```

On start it prints `VICO_READY port=<port>` to stdout. See `docs/api_contract.md` for the API.
