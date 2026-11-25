# Hearth — a personal assistant that lives in its own computer
Fly.io Hacksgiving 2026 entry (solo, Frank Zhu). Deadline Sun Nov 29 2026 11:59 PM PST.
Hard rules: runs on a Fly.io Sprite; uses >=1 Sprites connector; built Nov 23–29.

## Pitch
A Hark/Muse-style personal assistant whose whole self is one Sprite:
- Memory = plain markdown files on the Sprite disk (memory/USER.md, memory/people/*.md, memory/topics/*.md, memory/daily/YYYY-MM-DD.md). Agent reads/writes them via tools.
- Sleeps (free) when idle; wakes on HTTP request or scheduled job.
- Checkpoint-before-act: before any tool call that changes the outside world or its memory in bulk, it takes a Sprite checkpoint (`sprite-env checkpoints create --comment ...` from inside), and the UI shows an "Undo" that restores (`sprite-env checkpoints restore <id>`). This is the headline demo.
- Credentials never enter the Sprite: every external call goes through the Sprites gateway https://api.sprites.dev/v1/gateway/<provider>/<connection_id>/<path> (no Authorization header; gateway authenticates the Sprite).
- Approval gate: outbound actions (send email, post) are proposed as cards the user approves in the chat UI.

## Components
1. Web chat UI served on port 8080 (Sprite URL https://your-sprite.sprites.app). Single-page, clean, mobile-friendly. Streaming replies, action cards with Approve / Undo, a Memory tab showing the files, a Timeline tab showing checkpoints.
2. Agent loop (TypeScript/Node or Python, your choice; keep deps small) with tool calling:
   - memory_read / memory_write / memory_search
   - web_search (Tavily connector, optional)
   - send_email (AgentMail connector, optional, approval-gated)
   - schedule (cron-like jobs persisted on disk; a sprite-env service runs the scheduler)
   - checkpoint / undo
3. LLM provider adapter: primary Meta Muse Spark via Meta connector gateway; fallbacks Ollama Cloud / OpenRouter connectors. Config file config/connectors.json holds {provider, connection_id, model}. Until real connection IDs exist, include a MOCK provider so everything runs and tests pass offline.
4. Recall: Pinecone connector (judge sponsor) indexes memory files for semantic search; fall back to local keyword search if not configured.

## Deploy
- Local dev in this repo; deploy to Sprite "hearth" (org xuefeng-zhu). `sprite` CLI is on PATH and authenticated (env SPRITES_TOKEN is proxy-managed; do NOT print it). Use `sprite exec -s hearth -- ...`, copy files (e.g. tar via `sprite exec` stdin or git), and `sprite-env services create web ... --http-port 8080` inside the Sprite.
- scripts/deploy.sh does the whole deploy idempotently.
- Do NOT make the URL public (`--url-auth public`) without asking — leave default.

## Demo story (60s)
"Plan Thanksgiving dinner" → it remembers the family from memory, drafts guest emails (approval card), schedules a reminder, then a deliberately bad action (wipes a memory file) → Undo restores via checkpoint in ~1s.

## Deliverables this pass
- Working MVP with MOCK LLM + real checkpoint/undo on the Sprite + memory files + web UI + scheduler service.
- README with architecture, connectors used, how to run.
- Tests for agent loop, memory tools, approval gate.
