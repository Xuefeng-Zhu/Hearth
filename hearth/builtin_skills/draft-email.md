---
name: Draft an email
description: Write an email draft for review with a subject and message body.
when_to_use: The user asks to draft, compose, write, or revise an email.
tools: [memory_search, memory_read, send_email]
---
1. Check the request for its audience, purpose, and tone. Recall relevant details when needed and never guess a recipient address.
2. Present the subject and message in chat as a draft. Do not call `send_email` for a draft-only request.
3. If the user explicitly asks to send, use `send_email` to open the approval card. The user reviews and approves sending in that card.
