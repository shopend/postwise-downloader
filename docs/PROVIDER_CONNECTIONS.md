# Provider-independent AI connections for Postwise

Status: architecture specification, not implemented account connections.
Date: 2026-10-31

## Product goal

A user connects an eligible AI provider, chooses a model, and uses the same source-to-knowledge workflow with OpenAI, Anthropic Claude, Google Gemini, or another supported provider. Provider choice must not change ownership of source material or the structure of saved teaching notes.

App sign-in, provider authorization, and billing entitlement are three separate states. A successful account sign-in must never be presented as permission to run inference or to spend a subscription allowance.

## Two execution paths

### 1. Analysis in a connected assistant

Postwise exposes user-owned source material and note-writing operations through MCP. The user asks a supported assistant to read queued sources and save a note. The assistant runs under that host application's account, permissions and limits.

The existing ChatGPT plugin is this path. A browser click queues work; it does not itself initiate a turn in ChatGPT. Other assistant hosts require their own tested MCP authorization integration; do not label Claude or Gemini as connected merely because an MCP endpoint exists.

### 2. Analysis initiated inside Postwise

The user explicitly selects an authorized provider connection and a permitted model. Postwise's job runner calls that provider's documented inference endpoint through an adapter.

Use official account authorization where the provider permits this application and deployment type. Offer API credentials as a separately labeled, opt-in alternative where supported. Do not silently replace subscription usage with metered API usage.

## Provider eligibility at the design date

| Provider | Supported integration direction | Gate before enabling account-based inference |
| --- | --- | --- |
| OpenAI | Official Sign in with ChatGPT plan-usage flow for eligible integrations; OpenAI API alternative | Hosted/private app eligibility, registered client and approved callback, granted inference scopes, permitted models, usage limits |
| Claude | Claude API credentials or supported workload identity; external assistant MCP path requires validation | No general consumer Claude subscription authorization for this app has been established; provider-approved integration required before promising subscription-backed website inference |
| Gemini | Gemini API OAuth or API key; cloud project setup required | Registered OAuth application, appropriate verified scopes and project/API access; Google sign-in alone does not establish inference or subscription entitlement |
| Other providers | An explicit adapter implementing supported APIs and auth | Verify provider terms, official authorization, models, modalities, quotas and billing before enabling |

This is not a promise that any subscription can fund arbitrary third-party computation. Do not collect consumer passwords, browser cookies, or unrelated CLI session tokens.

## User interface

Connections page:
- Provider name and account label.
- Connection method: assistant-host connection, authorized account usage, or API credentials.
- Separate status for identity, inference permission and billing source.
- States: not connected, connecting, authorized, needs authorization, unsupported, error.
- Available model picker populated from verified access or a documented validated allowlist.
- Capability badges for text, image, audio/transcription and structured output.
- Reconnect and disconnect actions.
- Usage link and limits where supplied by the provider; unknown usage remains unknown.
- If account linking is unavailable, explain why and offer supported alternatives.

Analysis form:
1. Paste source URL.
2. Review retrieved caption, ordered images, video frame timestamps and transcript coverage.
3. Choose a connected provider and model.
4. Choose explanation language and optional learning focus.
5. Show the selected provider and billing source before an explicit Analyze action.
6. Show retrieval, frame extraction, transcription and explanation progress separately.
7. Save the completed knowledge entry with source provenance and execution metadata.

Never send a source to multiple providers without an explicit comparison action or a clearly authorized fallback preference.

## Adapter contract

Each adapter implements:
- getConnectionOptions(): methods actually configured and supported.
- beginAuthorization(): state, PKCE and registered callback for approved OAuth flows.
- completeAuthorization(): verify issuer/audience/state, exchange code and retain granted scopes.
- refreshAuthorization(): renew a grant using provider-documented behavior.
- disconnect(): revoke where supported and remove retained credentials.
- listModels(): return models the selected connection can use.
- getCapabilities(model): modalities, context/image limits, structured-output and streaming support.
- analyze(sourceBundle, teachingContract, model, connection): return a normalized teaching note.
- normalizeError(): authentication, permission, quota, rate limit, unsupported modality, provider failure.
- getUsage(): provider-reported usage if supported, otherwise explicitly unavailable.

Adapters own provider-specific request formats. They cannot change the task or use a different billing source without authorization.

## Common source and result contracts

SourceBundle:
- immutable source ID and original URL
- source metadata and retrieval coverage
- caption
- ordered images with source-item references
- timestamped sampled video frames and original clip mapping
- audio chunks and transcript, with timestamp and uncertainty information
- requested language and learner focus

TeachingNote:
- simple explanation
- essential theory and causal logic
- how it works, step by step, with a worked example
- reconstructed source outline
- reusable framework with inputs, decisions, actions, checks and outputs
- combinations with other tools and theories
- practical implementation steps
- realistic outcomes, prerequisites and success measures
- assumptions, evidence gaps and limitations
- understanding checks and next experiments
- transcript and source provenance
- provider, model, execution mode and connection ID
- generated timestamp and language

Preserve the same semantic structure across languages. Japanese translation should translate the existing note faithfully rather than silently generating a different analysis.

## Modality routing

Do not assume every LLM accepts video, audio or 60 images at once. Determine model capabilities before starting.
- Batch ordered frames within provider limits, preserving timestamps and cross-batch context.
- Use a separately authorized transcription provider if the selected model cannot handle audio.
- Ask or use an already selected explicit routing preference before sending audio to another provider.
- If transcription is missing, mark the result as visual-only and do not invent speech.
- Record sampled-frame gaps; never claim continuous viewing.

## Credentials and user isolation

Store provider credentials encrypted server-side using a deployment-owned encryption key or managed secret store. Never retain them in browser storage, GitHub, logs, notes, URLs, or prompts. Keep provider tokens separate from the existing importer token.

Connection records are scoped to the authenticated Postwise user. Authorize every source, connection, job and result access server-side. Use PKCE, expiring one-use state, exact redirect allowlists and CSRF protection. Avoid application-wide shared user credentials.

Disconnect must block new jobs immediately and revoke/erase retained grants where supported. App data deletion and provider revocation are separate operations.

## Jobs, errors and billing

Job states: queued, retrieving, extracting, transcribing, analyzing, saving, complete, failed, cancelled.
Use idempotency keys so double clicks do not create duplicate paid runs.
Keep partial sources/transcripts when a later phase fails. Retry bounded transient failures only; do not retry denied authorization or exhausted quota.
Do not automatically switch providers, models, accounts or billing modes on failure.
Expose actual provider usage if available; any cost estimate must be labeled and dated.
Assistant-host execution is not a continuously running website worker.

## Implementation sequence

1. Preserve the working ChatGPT MCP route and finish deploying the Instagram retrieval service.
2. Add connection records, capability registry, adapter interface and shared teaching-note validation.
3. Implement and test supported API adapters for OpenAI, Claude and Gemini using explicit user credentials.
4. Register and implement account OAuth only for approved providers/app types, with clear availability states.
5. Add job orchestration, progress, reconnect/disconnect, authorization isolation and usage handling.
6. Validate each path with real authorized accounts: text, images, video frames, audio/transcripts, Japanese output, expired credentials, quota errors and duplicate submissions.

## Current implementation boundary

The private repository currently contains the Instaloader/FFmpeg retrieval service, Dockerfile and Render Free configuration. The deployed Site currently has a ChatGPT MCP queue and an optional OpenAI API analysis path. Claude/Gemini execution, OAuth connection screens, a credential vault and the provider adapter layer are not implemented by this document.

## Official references

- https://developers.openai.com/siwc/quickstart
- https://developers.openai.com/siwc/token-sharing-open-source
- https://platform.claude.com/docs/en/manage-claude/authentication
- https://ai.google.dev/gemini-api/docs/oauth
