# Run 62 — D17 dead code cleanup

A search across `hearth/`, `web/`, `scripts/`, `tests/`, and `.github/` found no callers of `Integrations.configured` and one test caller of `Storage.search`. The test now checks that `Recall.run` returns `people/maya.md` among the top five keyword results for `vegetarian`. Both unused helpers were removed.

## Local verification

- `python -m unittest discover -s tests` passed all 241 tests with the project PDF font.
- `node --test tests/*.test.mjs` passed all 9 tests.
- `node --check` passed for all 25 `web/*.js` files.
