# Hearth status

Hearth's Fly.io Hacksgiving 2026 build runs as a private Sprite workspace. A fresh local checkout supports a Mock demo with sample memory and local artifacts. Provider actions depend on the connections and permissions granted to each deployment.

| Area | Shipped behavior |
| --- | --- |
| Home and Chat | Reorderable Home panels, streamed Main and side chats, attachments, and Ember on desktop and mobile |
| Approvals and Timeline | Policy categories, editable proposals where supported, expiry, decision records, and Undo for supported changes |
| Reminders and tasks | In-app reminders, email with AgentMail, recurring prompts, run history, and a scheduler wake hook |
| Artifacts and Pages | Local file generation, previews and downloads, Box sync, and versioned HTML pages with optional snapshot sharing |
| Memory | Markdown source files, local recall, optional Pinecone sync, and source citations |
| Voice | Browser or Whisper dictation, Vocal Bridge live calls, and a scripted call demo |

## Deployment notes

- Box version uploads are supported. Until the gateway supports the Box versions GET, history uses locally recorded receipts.
- Pinecone needs an index in the connected project. The dense setup uses `hearth-memory`, 384 dimensions, cosine similarity, and Hugging Face embeddings.
- Browserbase is optional and unconfigured in the demo deployment.
- Periodic scheduler wake and anonymous Page publishing are opt-in deployment steps.

[Setup](README.md) · [Connector status and setup](docs/connectors.md) · [QA and demo](QA-REPORT.md)
