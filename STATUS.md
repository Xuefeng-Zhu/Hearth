# Hearth status

Hearth's Fly.io Hacksgiving 2026 build runs as a private Sprite workspace. A fresh local checkout supports a Mock demo with sample memory and local artifacts. Provider actions depend on the connections and permissions granted to each deployment.

| Area | Shipped behavior |
| --- | --- |
| Home and Chat | Reorderable Home panels, streamed Main and side chats with rolling summaries, attachments, and Ember on desktop and mobile |
| Skills and workers | Versioned Markdown playbooks, in-chat skill approvals, cancellable parallel workers, and one combined reply |
| Feed and Goals | Steerable Feed with saved cards, one-tap Ideas with approvals, and Goals with check-ins and Timeline Undo |
| Approvals and Timeline | Policy categories, editable proposals where supported, expiry, decision records, and Undo for supported changes |
| Reminders and tasks | In-app reminders, AgentMail, recurring prompts, event automations with run history, and a scheduler wake hook |
| Artifacts and Pages | Local file generation, previews and downloads, Box sync, cited questions over Box files, and versioned HTML pages |
| Memory | Structured Markdown notes, English and Chinese recall, optional Pinecone sync, nightly proposals, and permanent forget |
| Voice | Browser or Whisper dictation, Vocal Bridge live calls, and a scripted call demo |

## Deployment notes

- Box version uploads are supported. Until the gateway supports the Box versions GET, history uses locally recorded receipts.
- Pinecone needs an index in the connected project. The dense setup uses `hearth-memory`, 384 dimensions, cosine similarity, and Hugging Face embeddings.
- Browserbase passed its read-only connection check on Nov 26, 2026. Run 34 used local Chromium to verify the Sprite UI and opened zero Browserbase sessions.
- Run 34 verified Box upload, parallel Exa search, and connected Whisper transcription with synthetic data on the Sprite.
- **Settings → Watchers** reports that Apify watchers are blocked. Approved page and price watchers use Hearth’s public-page reader. [Apify probe](docs/watchers.md)
- Box AI routes returned HTTP 403. Ask my files uses Hearth’s text extractors, Pinecone, and a connected brain. [Box probe](docs/box.md)
- Periodic scheduler wake and anonymous Page publishing are opt-in deployment steps.
- Run 48 checked production navigation in both themes at 375×667, 390×844, and 1440×1000, with fictional write tests on the same Sprite. [Run 48 QA](QA-REPORT.md#run-48)

[Setup](README.md) · [Connector status and setup](docs/connectors.md) · [QA and demo](QA-REPORT.md)
