# Web workspace design

The public page is a server-backed project workspace, not a device simulator.

## 2026-06-06 Gemini-style conversation update

- Opening the root URL always presents the account chooser instead of jumping into chat.
- Remembered accounts store usernames only; passwords and API credentials never enter local storage.
- A valid server session appears as an explicit continue-account choice.
- Conversations are independent server-side records with separate Hermes conversation identifiers.
- The left rail contains new-chat and recent-conversation controls.
- User messages align right, Hermes messages align left, and the composer stays at the bottom of the chat viewport.
- Only the chat viewport scrolls; the document and application shell remain fixed.

## 2026-06-06 Vela identity and interaction hardening

- Public identity is Vela; legacy project, model, framework, and server names are not shown.
- Login follows a quiet account-chooser pattern rather than explaining the product in marketing copy.
- Conversation switching uses request cancellation, sequence checks, and per-conversation caches.
- Conversations can be permanently deleted by their owner.
- The account chip is a direct navigation control.
- Query parameters are never used for authentication and are removed from the address bar.
- The server-knowledge page is removed from public navigation.

## 2026-06-06 Gemini sidebar interaction

- The application defaults to a white light theme.
- New chat, conversation search, and signal channels live at the top of the sidebar.
- The account switcher is anchored to the sidebar bottom.
- Conversation actions appear behind a three-dot menu and never use browser confirmation dialogs.
- The menu supports pin, inline rename, and immediate owner-scoped deletion.
- The sidebar can collapse without resetting the active conversation.

## Product surface

- Account login uses an `HttpOnly` server session cookie.
- Hermes chat calls FastAPI, which calls the loopback-only Hermes API Server.
- Chat history is stored per user on the server.
- Project documents list only files that exist in approved server directories.
- Hardware information is modeled as signal channels first.
- I2C starts with `SDA` and `SCL`; identified hardware appears beneath that channel.

## Deliberately removed

- Browser-side interface key storage
- Request ID and ACK controls
- Simulated telemetry
- Sensor-specific navigation
- Deployment history and raw MQTT dumps
- Demonstration-only device options

Hardware deployment APIs remain available for engineering compatibility, but they are not part of the current public web milestone.
