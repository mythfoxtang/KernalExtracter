# Tomorrow TODO

Date: 2026-04-22

## Goal

Add a mobile-friendly streaming answer experience without exposing secrets or noisy runtime data.

## Priority Tasks

1. Split answer generation into background runs.
2. Add a `run_id` for each capture request.
3. Return immediately from `POST /api/page-capture` with `run_id` instead of blocking until the model finishes.
4. Add a real-time status endpoint for the phone page.
5. Update the phone page so it shows:
   - direct answer first
   - streaming content below
   - clear running / done / failed state
6. Keep `ntfy` as a notification and deep-link layer, not as the streaming container.

## Suggested Architecture

### 1. Backend flow

- Current flow:
  - capture page
  - call model synchronously
  - write final log
  - phone page polls final result

- Target flow:
  - capture page
  - create `run_id`
  - create run state file
  - start background task
  - phone page subscribes to this run
  - stream progress and answer chunks
  - write final result on completion

### 2. Data model

Add one run record per request, for example:

```json
{
  "runId": "20260422-101530-ab12",
  "status": "queued",
  "createdAt": "2026-04-22T10:15:30+08:00",
  "updatedAt": "2026-04-22T10:15:30+08:00",
  "page": {
    "title": "",
    "url": ""
  },
  "answerMode": "reference",
  "directAnswer": "",
  "streamText": "",
  "finalAnswer": "",
  "error": ""
}
```

## Implementation Plan

### Step 1. Introduce run-based logging

- Add a new run directory, for example `page-answer-agent/agent_runs/`
- For each run:
  - `latest.json`
  - `{run_id}.json`

### Step 2. Make `POST /api/page-capture` non-blocking

- Save capture payload
- Create `run_id`
- Write initial state
- Start background worker
- Return JSON with:

```json
{
  "ok": true,
  "runId": "20260422-101530-ab12",
  "mobileUrl": "/mobile/run/20260422-101530-ab12"
}
```

### Step 3. Add streaming transport

Two acceptable options:

1. Polling first
   - easier
   - lower risk
   - enough for initial version

2. SSE second
   - cleaner realtime UX
   - lower overhead than frequent polling

Recommendation:
Start with polling, then upgrade to SSE if needed.

### Step 4. Split displayed content

Always keep two fields:

- `directAnswer`
  - first screen
  - short
  - always visible

- `streamText`
  - growing body content
  - partial reasoning / draft output / code

Do not expose private chain-of-thought claims. Show only user-visible generated content or explicit progress states.

### Step 5. Update phone page UX

Phone page should show:

- top card: direct answer
- middle card: live status
- body card: streaming content
- final state badge: success / failed
- copy button for final answer

## `ntfy` Strategy

Use `ntfy` only for:

1. "Task started, tap to view live result"
2. "Task finished"
3. "Task failed"

The live stream itself should happen on our own mobile page after the tap.

## Security Notes

- Never commit `page-answer-agent/.env.local`
- Never commit runtime logs by default
- Never commit captured page data by default
- If a public repo is created, review logs and screenshots before any manual upload

## Open Questions

1. Do we want polling first or go directly to SSE?
2. Should phone page keep one global "latest run" URL plus per-run URLs?
3. Do we want to stream only answer text, or also explicit progress events like:
   - task detected
   - answer generating
   - final formatting

## First Files To Change Tomorrow

- `page-answer-agent/page_capture_server.py`
- `page-answer-agent/agent.py`
- `page-answer-agent/README.md`

## Definition Of Done

- phone can open one live run URL
- page updates before final completion
- top of page always shows direct answer first
- no `.env.local`, logs, or captures are tracked by git
