# Run 45 — Watchers gateway probe

The live probe ran from the deployed Hearth Sprite on November 26, 2026, at 04:06–04:07 UTC. Sprites gateway discovery returned one Apify connection. The connection's usage example specified `GET /v2/actors?limit=1`. That request returned HTTP 200 and one Actor entry through the gateway.

| Read-only request through the Apify connector | Result |
| --- | --- |
| `GET /v2/acts?limit=1` | HTTP 403 |
| `GET /v2/actors/apify~website-content-crawler` | HTTP 403 |
| `GET /v2/users/me` | HTTP 403 |
| `GET /v2/users/me/limits` | HTTP 403 |
| `GET /v2/users/me/usage/monthly` | HTTP 403 |
| `GET /v2/actors/apify~website-content-crawler/runs?limit=1` | HTTP 403 |
| `GET /v2/actor-runs?limit=1` | HTTP 403 |
| `GET /v2/datasets?limit=1` | HTTP 403 |

Each HTTP 403 carried the gateway error `endpoint is not supported by the Apify connector`. Paths in the table are relative to the discovered Apify connection.

The successful list call confirmed access to that route. The rejected account reads left the connected account's Free plan and usage unverified. Fly documents that starting an Actor can use credits or incur charges. The run stopped before sending an Actor-start request. No Actor run was created, and reading its dataset remains unverified. [Fly's Apify connector setup](https://fly.io/sprites/ecosystem/), [Apify's account endpoint](https://docs.apify.com/api/v2/users-me-get), [Apify's Free plan](https://docs.apify.com/account/subscriptions#try-apify-for-free)

Run 45 ended at this probe. Watcher implementation, deployment, and end-to-end verification remain pending.
