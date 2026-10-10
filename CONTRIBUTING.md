# Contributing

Thanks for helping. Issues and pull requests are welcome in English or Spanish.

- **Before a large change** (a new built-in card, a new dependency, a change to the state
  format), open an issue to agree on the approach. Small fixes can go straight to a PR.
- **Setup**: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.
- **Checks** (CI runs the same, on Python 3.11 and 3.12):

  ```sh
  .venv/bin/ruff check . && .venv/bin/ruff format --check .
  .venv/bin/python -m pytest -q
  ```

- **Tests** must not need the LCD, asterctl, root or network: use synthetic data
  (`Card.sample()`), monkeypatched readers and the fake asterctl in `tests/test_asterctl.py`.
  Every new card needs a test that renders it at 960x376 with sample, missing and garbage data.
- **Screenshots**: if a card changes visually, regenerate them with
  `sh scripts/make-screenshots.sh` and commit `docs/img/`. Never use real host names,
  addresses or data from your own machines in screenshots, examples or issues.
- **Docs**: update `README.md` and `README.es.md` together, plus `config.example.yaml` when
  an option changes.
- **asterctl**: do not copy its code into this repository. To move to a new release, update
  `asterctl.version` (tag, commit, SHA-256) and `PINNED_TAG` in `src/aoostar_lcd/asterctl.py`;
  the tests and the CI job "asterctl pin" check that they agree.
- **Commits**: one logical change per commit, message in English explaining why.

By contributing you agree that your work is released under the MIT License and that you
follow the [Code of Conduct](CODE_OF_CONDUCT.md).
