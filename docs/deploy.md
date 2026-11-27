# Deploy to a Fly Sprite

## Deploy your own

1. On GitHub, select **Use this template** or fork Hearth. For a fork, enable workflows in your copy’s **Actions** tab. [GitHub workflow dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
2. In the Fly dashboard, select your organization and create a Sprites access token with permission to create and manage the target Sprite. In your GitHub copy, open **Settings → Secrets and variables → Actions** and add it as the `SPRITES_TOKEN` repository secret. [Sprites access tokens](https://fly.io/run-agent-code/)
3. Open **Actions → Deploy to my Sprite → Run workflow**. Use `hearth` or enter another `sprite_name`. The optional `org` input takes a Fly organization slug. When left blank, the workflow uses the `HEARTH_SPRITE_ORG` repository variable if set, or the token’s organization. The workflow creates or reuses the named Sprite, sets URL authentication to **Sprite**, deploys the selected revision, and checks `/health`. [Manual workflow](../.github/workflows/deploy-my-sprite.yml)
4. Open your Sprite from the Fly dashboard. Under **Sprites → Connectors**, add providers such as Hugging Face and grant access to the Sprite name you chose. In Hearth, open **Settings → Connections** and select **Refresh**. [Connector setup](connectors.md)

[Local quick start](../README.md#quick-start)

## Deploy from the CLI

Install and authenticate the Sprites CLI. Run the deployment from a Linux shell with GNU tar. Create a Sprite named `hearth` in the CLI's selected organization and keep its URL authentication set to **Sprite**. The workspace uses that authentication for access. [Sprites quickstart](https://docs.fly.io/sprites/quickstart), [Sprite HTTP access](https://docs.fly.io/sprites/working-with-sprites#http-access)

```sh
sprite create hearth --skip-console
scripts/deploy.sh
sprite exec --http-post --no-stdin --no-port-forward -s hearth -- curl -fsS http://127.0.0.1:8080/health
```

If you use multiple organizations, select the right one in the CLI or export `HEARTH_SPRITE_ORG` before running the Hearth scripts. When calling `sprite` directly, pass the CLI's `-o` flag for that organization. Set `HEARTH_SPRITE_NAME` when running `scripts/deploy.sh` to deploy to an existing Sprite with a name other than `hearth`.

The deploy script uploads runtime files and seed memory. The installer extracts a content-addressed release, installs dependencies in the shared `~/hearth/.venv`, installs the PDF font, switches the `current` symlink, and starts or restarts the web and scheduler services. A successful loopback probe returns `{"ok": true, "checkpoints": "sprite"}`. A failed probe exits with the new release still selected. Use the Sprite's entry in the Fly dashboard to open the workspace. [Deploy script](../scripts/deploy.sh), [Installer](../scripts/install-sprite.sh)

## GitHub Actions

The **Test and deploy Hearth** workflow runs tests on pushes to `main`, pull requests into `main`, and manual dispatch. Its deploy job is restricted to the upstream `Xuefeng-Zhu/Hearth` repository and `main` pushes or dispatches. Deployment requires the Python and Node suites, JavaScript syntax checks, both offline Chromium runs, and the `SPRITES_TOKEN` repository secret. The upstream workflow uses `HEARTH_SPRITE_ORG` if set. [Deploy workflow](../.github/workflows/deploy.yml), [Local browser commands](testing.md#offline-chromium-smoke)

## Verify workspace access

Check that the workspace URL uses **Sprite** authentication. The installer's loopback health probe checks liveness. To verify signed-out access at the edge, run `scripts/check-edge-auth.sh` with the disposable workspace and public Page fixtures. The matrix runs manually outside deploy CI. `/api/status` is available behind the workspace edge for subsystem diagnostics. [Edge matrix](testing.md#signed-out-edge-authorization-matrix), [Subsystem status](architecture.md#status-and-stale-data)

## Wake the scheduler

A sleeping Sprite can catch up when a browser request or an external job wakes it. For closed-browser scheduling, arrange an external tick. On an authenticated CLI host, run:

```sh
scripts/wake.sh
```

The script calls `POST /api/scheduler/tick` from inside the Sprite with the workspace's tick token. Alternatively, give the script `HEARTH_SPRITE_URL`, `HEARTH_TICK_TOKEN`, and `SPRITE_API_TOKEN` as environment secrets for authenticated HTTP wake. The tick token is generated under `~/hearth/data/scheduler-tick.token`. The [wake workflow template](../.github/workflows/wake.yml.example) is inactive as shipped. To enable it, set the three GitHub Actions secrets and save the template as `.github/workflows/wake.yml` on the default branch. Its five-minute schedule can add a polling interval plus scheduling delay. Hearth records late reminder deliveries on catch-up. [Wake script](../scripts/wake.sh), [Sprite lifecycle](https://docs.fly.io/sprites/working-with-sprites)

A successful tick reports reminder claims and eligible queued deliveries. Delivery, Inbox, tasks, and refreshes can still be running after the response. A checkpoint restore can temporarily pause new scheduler claims across both services. [Delivery and restore](approvals-and-tasks.md#scheduler-delivery-and-restore)

## Publish HTML snapshots

After deploying the private workspace, run `scripts/deploy-pages-share.sh` if you want anonymous sharing. It creates or updates a separate Sprite named `hearth-pages`, stores the publisher configuration privately, and enables public URL access for that Sprite. From an HTML artifact's preview, request a share link and approve the specific version. Use **Revoke link** to remove the published snapshot. Later edits create new private versions. [Publisher script](../scripts/deploy-pages-share.sh), [Pages implementation](../hearth/pages.py)
