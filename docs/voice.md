# Voice

## Dictation

Use the mic in Chat to record. Click again to finish, or hold **Space** in an empty composer and release it. **Escape** cancels. The transcript normally lands in the composer for review. Turn on **Send automatically after transcription** in **Settings → Voice** to submit it automatically.

**Auto** selects Hugging Face Whisper when the connection is authorized and Browser otherwise. Browser sends speech to the browser's speech recognition service where supported. Whisper sends audio through the Sprites gateway to Hugging Face's `openai/whisper-large-v3-turbo`. Set a language or use automatic detection. The default recording limit is 60 seconds. The mic needs HTTPS or localhost and browser permission. [Transcription adapter](../hearth/voice.py), [Browser controls](../web/voice.js)

## Live calls with Vocal Bridge

1. Create and deploy a Vocal Bridge voice agent. Set **AI Agent Integration** to the **client data channel**.
2. Add the agent-scoped key to the Vocal Bridge connector in Fly and grant the Hearth Sprite access.
3. Refresh **Settings → Connections** in Hearth. In a chat, select **Call**. The call sheet shows elapsed time, captions as they arrive, mute, minimize, and hang-up controls.

[Vocal Bridge developer guide](https://vocalbridgeai.com/docs/overview), [Fly setup](connectors.md)

The server asks Vocal Bridge for a short-lived room credential and returns it to the browser with `Cache-Control: no-store`. The browser joins LiveKit and sends the selected language as a context hint. When the agent delegates a question, the browser forwards it to Hearth in the chat that started the call. Hearth uses its normal memory and tools, with the same approval policy.

When the call ends, Hearth saves a duration card and, by default, redacted captions. Change the default 10-minute limit, language, or caption saving in **Settings → Voice**. With caption saving off, the duration card and any normal chat turns remain. When Vocal Bridge is disconnected, **Call** opens a labeled, scripted demo. [Token and transcript handling](../hearth/voice_call.py), [Call UI](../web/voice-call.js)
