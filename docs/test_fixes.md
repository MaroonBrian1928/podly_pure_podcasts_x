# Test Fixes

Pre-existing tech debt surfaced by `scripts/ci.sh`. CI ends with `All
checks passed!` but pytest reports ~150 warnings in the summary. These
do not indicate failing tests — they're cleanup targets, documented here
so they don't get mistaken for regressions when reviewing new changes.

## Known CI warnings

| Approx count | Type | Source | What it is |
|---:|------|--------|------------|
| ~140 | `LegacyAPIWarning` | `src/app/config_store.py` lines 170–174 + 354, `src/tests/test_config_store_output.py:38`, `src/tests/test_env_var_authority.py:112,419`, plus cascades through `flask_sqlalchemy/query.py:30` | `Model.query.get(pk)` — SQLAlchemy 1.x's `Query.get()`. The 2.0 form is `db.session.get(Model, pk)`. Fires once per test that exercises `ensure_defaults_and_hydrate()`, which is most of the config / route fixtures. |
| ~24 | `PydanticDeprecatedSince211` / `DeprecationWarning` | `src/app/config_store.py:1012–1013`, `src/shared/config.py:229` | `cfg.model_fields.keys()` on a Pydantic *instance* is deprecated as of Pydantic 2.11 — should be `type(cfg).model_fields`. The `config.py:229` one reads a `@deprecated` whisper field. |
| 2 | `PytestCollectionWarning` | `src/shared/config.py:64` (`class TestWhisperConfig(BaseModel)`) | Pytest tries to collect the class because of the `Test*` name prefix; it's actually a Pydantic model. Fix is `__test__ = False` on the class or rename. |

## Suggested approach

When fixing one, prefer fixing the whole family in one PR:

- For the SQLAlchemy migration: search for `.query.get(` and convert each
  to `db.session.get(Model, pk)`.
- For the Pydantic deprecation: search for `cfg.model_fields` (or any
  `<instance>.model_fields`) and switch to the class form.
- The `TestWhisperConfig` collection warning is a one-line fix
  (`__test__ = False`) or a rename.

Once all three are resolved, consider adding `-W error` (or a tighter
`filterwarnings` rule) to the pytest config so future regressions fail
CI instead of silently accumulating.
