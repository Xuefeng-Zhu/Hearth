# Run 95 · Deploy to my Sprite

Forks and template copies can deploy from GitHub Actions using a `SPRITES_TOKEN` repository secret. **Deploy to my Sprite** defaults to `hearth` and accepts a custom Sprite name and an optional Fly organization slug. Organization selection uses the `org` input first, then `HEARTH_SPRITE_ORG` if set, and otherwise the token’s organization. [Deployment guide](deploy.md#deploy-your-own)

The workflow looks up the exact Sprite and creates it on a `404`. It sets URL authentication to **Sprite** before uploading the release, probes `/health` inside the Sprite, and writes the Fly dashboard and connector setup steps to the summary. CLI and deploy output stay out of the workflow logs. The existing deploy job runs only in `Xuefeng-Zhu/Hearth` and still skips deployment when the token is missing. Both workflows share a concurrency group within the upstream repository. [Manual workflow](../.github/workflows/deploy-my-sprite.yml), [Upstream workflow](../.github/workflows/deploy.yml), [Sprites API lookup](https://docs.fly.io/sprites/api/sprites/get-a-sprite), [Sprite URL authentication](https://docs.fly.io/sprites/working-with-sprites#http-access)

## Verification

- Python passed 344 tests with the Chinese PDF font, including the new regression for the default `hearth` target and a custom name and organization. Node passed 37 tests.
- PyYAML loaded both workflows because actionlint was unavailable in `/workspace/tools/bin`. Bash syntax checks passed for all seven shell scripts and both workflows’ shell steps. ShellCheck was unavailable.
- Eleven local workflow scenarios covered creation, reuse, missing credentials, failures, the health probe, and log and summary privacy. The installed Sprites CLI returned the expected `200` and `404` status codes against a loopback fixture with and without `-o`. Local checks also covered the upstream repository guard and missing-token step conditions.
- Verification used local fixtures throughout. The commit was made locally on `main`.
