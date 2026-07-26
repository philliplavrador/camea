"""tests/guard/ — test-only benchmark helpers that must NOT ship in the installable wheel.

`score.py` scores a mosaic build against the hand-verified ground truth. It carries dataset-shaped
knowledge (the 260620d denominators, trial ranges and filenames), which is exactly why it lives here
under `tests/` and not under `src/camea/`: HARD RULE — the app carries no dataset knowledge, and now
neither does anything pip installs. Its only callers are the regression guards under `tests/`.

Importable as `from guard import score` because `pyproject.toml`'s `[tool.pytest.ini_options]`
`pythonpath = ["tests"]` puts `tests/` on `sys.path` for the whole session.
"""
