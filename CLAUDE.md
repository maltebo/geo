# Quality Gate

After every major work step, run the full pipeline and confirm all three pass before considering the work done:

```
ruff check . && ruff format --check . && mypy && pytest -q -m "not integration"
```

These must be green. Fix any failures before moving on.
