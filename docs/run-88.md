# Run 88 · Default weather location and privacy cleanup

Hearth now defaults to San Francisco, CA (`37.7749`, `-122.4194`) with the `America/Los_Angeles` time zone. The Home settings placeholder uses the same city. Hearth discards cached forecasts for the previous built-in default and keeps explicitly saved locations and their cached forecasts. The tests cover the new coordinates, the first refresh after an upgrade, and a custom location across workspace restarts.

The production acceptance report uses generic descriptions for the persona and places. The city-specific URLs were removed, and the measurements and findings were preserved. OCR found the old city in two desktop Home screenshots. Both were recaptured at 1440 × 1000 from the original QA revision (`925150b`) with an offline fictional workspace. [Acceptance report](../REAL-USER-TEST.md), [Dark screenshot](screenshots/qa5/home-1440-dark.png), [Light screenshot](screenshots/qa5/home-1440-light.png)

The tracked-content and filename scans found no remaining matches for the city, ZIP code, street fragment, or other supplied personal identifiers. The checks included `docs/` and screenshot filenames. OCR across the 73 tracked screenshots found no remaining matches after the two replacements.

**Older commits in Git history still contain the owner's city, including in the original screenshots.**

## Verification

| Check | Result |
| --- | --- |
| Python unittest discovery with `HEARTH_CJK_FONT` | 343 passed |
| Node unit tests | 37 passed |
| `node --check` | All 63 frontend JavaScript modules passed |
| Playwright Chromium | Default smoke, stream disconnect, Chat search, list search, and motion passed |
| Run 22 Chromium weather flow | Desktop light profile passed with the new default and a saved custom location |

## Deployment

`scripts/deploy.sh` deployed `7741f4694390fb14fd781ffaf6467b31c0ef3d0a` to the private `hearth` Sprite. A separate `/health` request returned HTTP 200 with the same SHA and Sprite checkpoints. Both commits are local.
