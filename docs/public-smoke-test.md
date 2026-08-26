# Public smoke test

`scripts/smoke_public_release.py` is a repeatable, read-only smoke test for
the deployed Rightly site and the published Windows-installer metadata. It is
intended for release readiness and judge-demo checks; it does **not** download
the installer or any model.

## Run

```powershell
python scripts/smoke_public_release.py `
  --json-out tmp/public-smoke.json `
  --markdown-out tmp/public-smoke.md
```

The command returns `0` only when every contract passes, otherwise `1`.
Override `--base-url` or `--release-api` for a preview/release candidate.

## Contracts checked

- root landing page and `/health` public API readiness;
- `/api/chat` deterministic arithmetic;
- Vietnamese red-light prompt with accents, without accents, and a bounded
  spelling typo; each must ask for vehicle type rather than invent a fine;
- out-of-scope weather answer;
- `/api/chat/stream` SSE final-answer/delta contract;
- v0.18.0-pilot release metadata containing a non-empty HTTPS
  `Rightly-Setup.exe` asset.

The script sends only fixed synthetic prompts and its reports include status,
latency and pass/fail notes only. It never writes response bodies, credentials,
history, participant data or downloaded files.
