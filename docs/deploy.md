# Deploy to a Fly Sprite

Install and authenticate the Sprites CLI. Run the deployment from a Linux shell with GNU tar. Create a Sprite named `hearth` in the CLI's selected organization and keep its URL authentication set to **Sprite**. The workspace uses that authentication for access. [Sprites quickstart](https://docs.fly.io/sprites/quickstart), [Sprite HTTP access](https://docs.fly.io/sprites/working-with-sprites#http-access)

```sh
sprite create hearth --skip-console
scripts/deploy.sh
sprite exec --http-post --no-stdin --no-port-forward -s hearth -- curl -fsS http://127.0.0.1:8080/health
```

If you use multiple organizations, select the right one in the CLI or export `HEARTH_SPRITE_ORG` before running the Hearth scripts. When calling `sprite` directly, pass the CLI's `-o` flag for that organization.

The deploy script uploads runtime files and seed memory. The installer extracts a content-addressed release, installs dependencies and the PDF font, switches the `current` symlink, and starts or restarts the web and scheduler services. A successful probe returns `{"ok": true, "checkpoints": "sprite"}`. Use the Sprite's entry in the Fly dashboard to open the workspace. [Deploy script](../scripts/deploy.sh), [Installer](../scripts/install-sprite.sh)

## GitHub Actions

Set the repository secret `SPRITES_TOKEN` to a Sprites token authorized for the deployment organization. If the CLI needs explicit organization selection, set the repository variable `HEARTH_SPRITE_ORG`. The workflow runs on pushes to `main` and on manual dispatch. Its deploy job depends on the unit tests and the offline Chromium smoke, and skips deployment when the secret is empty. [Deploy workflow](../.github/workflows/deploy.yml)

## Wake the scheduler

A sleeping Sprite can catch up when a browser request or an external job wakes it. For closed-browser scheduling, arrange an external tick. On an authenticated CLI host, run:

```sh
scripts/wake.sh
```

The script calls `POST /api/scheduler/tick` from inside the Sprite with the workspace's tick token. Alternatively, give the script `HEARTH_SPRITE_URL`, `HEARTH_TICK_TOKEN`, and `SPRITE_API_TOKEN` as environment secrets for authenticated HTTP wake. The tick token is generated under `~/hearth/data/scheduler-tick.token`. The [wake workflow template](../.github/workflows/wake.yml.example) is inactive as shipped. To enable it, set the three GitHub Actions secrets and save the template as `.github/workflows/wake.yml` on the default branch. Its five-minute schedule can add a polling interval plus scheduling delay. Hearth records late reminder deliveries on catch-up. [Wake script](../scripts/wake.sh), [Sprite lifecycle](https://docs.fly.io/sprites/working-with-sprites)

## Publish HTML snapshots

After deploying the private workspace, run `scripts/deploy-pages-share.sh` if you want anonymous sharing. It creates or updates a separate Sprite named `hearth-pages`, stores the publisher configuration privately, and enables public URL access for that Sprite. From an HTML artifact's preview, request a share link and approve the specific version. Use **Revoke link** to remove the published snapshot. Later edits create new private versions. [Publisher script](../scripts/deploy-pages-share.sh), [Pages implementation](../hearth/pages.py)
