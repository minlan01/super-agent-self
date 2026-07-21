# API Reference

**Version**: 2.2.0
**Base URL**: `http://localhost:8000`

All endpoints return JSON. The standard response wrapper includes `success: bool` and `message: str`.

**Error responses** always follow the format `{"success": false, "message": "description"}` for 400, 404, 422, and 500 errors.

## Common Query Parameters

Paginated endpoints accept `page` (default 1, min 1) and `page_size` (default 20, min 1, max 100).

---

## Health

### GET /health

Basic service health check.

**Response** `200 OK`

```json
{
  "status": "ok",
  "version": "2.2.0",
  "edition": "enterprise"
}
```

### GET /api/v1/health/ready

Deep readiness probe — checks DB connectivity.

**Response** `200 OK`

```json
{
  "ready": true,
  "checks": {
    "db": "ok"
  }
}
```

### GET /api/v1/health/metrics

Platform metrics — task counts, memory counts, uptime.

**Response** `200 OK`

```json
{
  "tasks": {"pending": 3, "completed": 12, "failed": 1},
  "total_tasks": 16,
  "memories": {"total": 45, "active": 38},
  "uptime_seconds": 3600,
  "version": "2.0.0"
}
```

---

## Tasks

### POST /api/v1/tasks

Create a new task.

**Body**:
```json
{
  "goal": "Open example.com and extract text",
  "edition": "enterprise",
  "user_id": "default"
}
```

**Response** `201 Created`

### GET /api/v1/tasks

List tasks with optional filters.

**Query params**: `status`, `edition`, `page`, `page_size`

### GET /api/v1/tasks/{task_id}

Get task details.

### POST /api/v1/tasks/{task_id}/cancel

Cancel a task.

### GET /api/v1/tasks/{task_id}/steps

Get task steps.

### GET /api/v1/tasks/{task_id}/audit

Get audit events for a task.

### POST /api/v1/tasks/{task_id}/retry

Retry a failed or completed task (resets to pending).

**Response** `200 OK`

### POST /api/v1/tasks/batch

Create multiple tasks at once (max 50).

**Body**:
```json
{
  "tasks": [
    {"goal": "Task 1", "edition": "enterprise"},
    {"goal": "Task 2", "edition": "enterprise"}
  ]
}
```

**Response** `201 Created`
```json
{
  "created": [...],
  "count": 2
}
```

---

## Memory

### GET /api/v1/memory/search

Search memories by keyword.

**Query params**: `q` (keyword), `edition`, `memory_type`, `limit`

### GET /api/v1/memory

List memories with pagination.

**Query params**: `edition`, `memory_type`, `page`, `page_size`

### GET /api/v1/memory/{memory_id}

Get memory details.

### POST /api/v1/memory/{memory_id}/disable

Disable a memory.

### DELETE /api/v1/memory/{memory_id}

Delete a memory.

---

## Skills

### GET /api/v1/skills

List skills with filters.

**Query params**: `edition`, `status`, `page`, `page_size`

### GET /api/v1/skills/{skill_id}

Get skill details.

### POST /api/v1/skills/{skill_id}/approve

Approve a candidate skill.

### POST /api/v1/skills/{skill_id}/disable

Disable a skill.

### POST /api/v1/skills/{skill_id}/rollback

Rollback skill to previous version.

---

## Audit

### GET /api/v1/audit

List audit events.

**Query params**: `event_type`, `task_id`, `page`, `page_size`

---

## Approvals

### GET /api/v1/approvals

List approval requests.

**Query params**: `status`, `approval_type`, `page`, `page_size`

### GET /api/v1/approvals/{approval_id}

Get approval details.

### POST /api/v1/approvals/{approval_id}/resolve

Resolve (approve or reject) an approval.

**Body**:
```json
{
  "action": "approve",
  "approved_by": "admin",
  "reason": "Looks safe"
}
```

---

## Personal Edition

### GET /api/v1/personal/reminders

List reminders. **Query params**: `include_expired`, `edition`

### POST /api/v1/personal/reminders

Create a reminder.

**Body**:
```json
{
  "title": "Check deploy",
  "remind_at": "2026-05-10T09:00:00Z",
  "context": "Production deploy scheduled"
}
```

### POST /api/v1/personal/reminders/{reminder_id}/dismiss

Dismiss a reminder.

### GET /api/v1/personal/context

Get aggregated personal context (preferences, reminders, memories).

### POST /api/v1/personal/preferences

Save a user preference.

**Body**:
```json
{
  "key": "preferred_language",
  "value": "python"
}
```

---

## Editions

### GET /api/v1/editions

List available editions.

### GET /api/v1/editions/{edition}

Get edition configuration.

---

## Chat

### POST /api/v1/chat

Send a conversational message. Intent is auto-detected (task, reminder, preference, info).

**Body**:
```json
{
  "message": "Open example.com and extract all headings",
  "user_id": "default",
  "edition": "enterprise"
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "intent": "task",
    "response": "Creating task to open example.com...",
    "task_id": "uuid-here"
  }
}
```

---

## Voice

### POST /api/v1/voice/stt

Upload audio file for speech-to-text transcription.

**Content-Type**: `multipart/form-data`
**Field**: `file` (audio file)

**Response**:
```json
{
  "success": true,
  "data": {
    "transcript": "open example.com"
  }
}
```

### POST /api/v1/voice/tts

Convert text to speech.

**Body**:
```json
{
  "text": "Task completed successfully",
  "voice": "default"
}
```

### POST /api/v1/voice/command

Route a voice transcript to an action.

**Body**:
```json
{
  "action": "browse",
  "transcript": "open example.com",
  "confidence": 0.8
}
```

---

## WebSocket

### WS /ws/tasks/{task_id}

Real-time task progress updates.

**Protocol**:
- Client sends `"ping"` to keep alive
- Server sends JSON task updates: `{"status": "executing", "step": 2, "message": "..."}`
- Server responds `"pong"` to pings

---

## Cron Scheduling

### POST /api/v1/cron

Create a scheduled task.

**Body**:
```json
{
  "name": "Daily report",
  "schedule": "every 60m",
  "goal": "Generate daily summary report",
  "edition": "enterprise",
  "enabled": true,
  "context_from": []
}
```

### GET /api/v1/cron

List all scheduled tasks.

### GET /api/v1/cron/{job_id}

Get a scheduled task.

### PUT /api/v1/cron/{job_id}

Update a scheduled task.

### DELETE /api/v1/cron/{job_id}

Delete a scheduled task.

---

## Conversations

### GET /api/v1/conversations

List conversations.

**Query params**: `user_id`, `limit`, `offset`

### GET /api/v1/conversations/{conversation_id}

Get a conversation with all messages.

### DELETE /api/v1/conversations/{conversation_id}

Delete a conversation and all its messages.

---

## Export

### GET /api/v1/export/tasks

Export all tasks as JSON or CSV.

**Query params**: `format` (`json` | `csv`, default: `json`)

### GET /api/v1/export/memories

Export all memories as JSON or CSV.

**Query params**: `format` (`json` | `csv`, default: `json`)

### GET /api/v1/export/audit

Export all audit events as JSON or CSV.

**Query params**: `format` (`json` | `csv`, default: `json`)

---

## Files

### GET /api/v1/files/{path}

Download a file from the workspace directory. Path traversal is blocked — only files within the workspace root are accessible.

**Response**: Binary file download (`application/octet-stream`), or `404` if not found.

---

## Rate Limiting

All endpoints (except `/health`) are rate-limited to 60 requests per minute per client IP. Exceeding the limit returns:

**Response** `429 Too Many Requests`
```json
{
  "success": false,
  "message": "Rate limit exceeded"
}
```

Header `Retry-After` indicates seconds until the limit resets.

---

## Error Responses

All errors follow the same format:

```json
{
  "success": false,
  "message": "Error description"
}
```

| Status | Meaning |
|--------|---------|
| 400 | Bad request (validation error) |
| 404 | Resource not found |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
