# Platform Roadmap — P0 / P1 / P2 / P3

> Last updated: 2026-05-19

## P0 — Foundation (Completed)

### P0-A: Unified Tool Registry
- Decorator self-registration pattern (`@tool_registry.register()`)
- YAML-code merge policy (YAML > decorator > class attribute)
- Singleton `UnifiedToolRegistry` with `get_instance()`
- Auto-import mechanism via `packages/executor/tools/_auto_import.py`
- Configuration: `configs/tools.yaml`

### P0-B: LLM Multi-Provider + Failover
- Abstract `BaseLLMProvider` with `generate()`, `generate_json()`, `stream()`
- Providers: DeepSeek (OpenAI-compatible), Anthropic, Ollama, Gemini, Mock
- `ProviderRouter` with failover chains and health tracking
- `CredentialPool` for round-robin API key rotation
- `ProviderHealthTracker` with consecutive failure counting and rate-limit cooldown
- `CostTracker` with per-request cost estimation
- Exponential backoff with jitter on retries
- Configuration: `configs/models.yaml`

---

## P1 — Multi-Platform Messaging Gateway (Completed)

### Architecture
- Mirrors `llm_gateway` pattern: `BaseMessagingProvider(ABC)` → platform implementations
- `MessagingRouter` with unified dispatch, failover chains, and credential pooling
- Reuses `CredentialPool` and `ProviderHealthTracker` from `packages/llm_gateway`

### Platform Providers
| Platform | File | Webhook Validation | Health Check |
|----------|------|--------------------|-------------|
| Telegram | `telegram_provider.py` | HMAC-SHA256 | `/getMe` |
| Discord | `discord_provider.py` | Ed25519 signature | `/users/@me` |
| Slack | `slack_provider.py` | HMAC-SHA256 + Signing Secret | `/auth.test` |
| Feishu | `feishu_provider.py` | Verification token + challenge | Tenant token cache |

### New Files
- `packages/messaging_gateway/` — base, providers, router
- `packages/db/repositories/messaging_repo.py` — channel + message log CRUD
- `apps/api_server/routes/webhooks.py` — webhook + messaging API routes
- `packages/executor/tools/messaging_tool.py` — `message.send` tool with safety check
- `configs/messaging.yaml` — platform configuration

### New DB Models
- `MessagingChannel` (table 15) — platform channel registration
- `MessageLog` (table 16) — inbound/outbound message log

### API Endpoints
- `POST /api/v1/webhooks/{platform}` — receive inbound webhooks
- `POST /api/v1/messaging/send` — send outbound message
- `GET /api/v1/messaging/channels` — list channels
- `POST /api/v1/messaging/channels` — register channel
- `GET /api/v1/messaging/history/{channel_id}` — message history

---

## P2 — CLI Terminal + Profile Isolation + Skill Marketplace (Completed)

### P2-A: CLI Core (typer + REPL)
- `apps/personal_shell/cli.py` — typer app with subcommands
- `apps/personal_shell/repl.py` — prompt_toolkit REPL with slash commands
- `apps/personal_shell/commands/task.py` — task CRUD commands
- `apps/personal_shell/commands/skill.py` — skill list/approve commands
- `apps/personal_shell/commands/config.py` — config show/edition switch
- CLI entry point: `myself` (via `pyproject.toml` `[project.scripts]`)

### P2-B: Streaming Output + Chat History
- `apps/personal_shell/streaming.py` — streaming via `ProviderRouter.stream()` → rich.Console
- `apps/personal_shell/history.py` — `ChatHistory` class with ConversationRepository persistence
- REPL slash commands: `/sessions`, `/history`, `/search`

### P2-C: CLI Tool Execution
- `apps/personal_shell/executor.py` — direct tool invocation from CLI/REPL
- Policy check + edition gate + safety check before execution
- Synthetic `ExecutionContext` for standalone tool runs

### P2-D: Edition Context Middleware
- `get_user_edition()` FastAPI dependency in `dependencies.py`
- Priority: `X-Edition` header > user profile > settings default
- Available to all route modules via `Depends(get_user_edition)`

### P2-E: Cache Key Isolation
- `packages/cache/manager.py` — `user_id` parameter on `get()`, `set()`, `invalidate()`
- Key format with user: `{prefix}:{namespace}:u:{user_id}:{key}`
- Backward compatible: omitting `user_id` uses classic format

### P2-F: User-Scoped Skill Marketplace
- `packages/skills/marketplace.py` — `SkillMarketplace` class
- Browse/search with filters (edition, category, min_rating, sort)
- Subscribe/unsubscribe per user
- Rate and review (1-5 stars + optional review text)
- `apps/api_server/routes/marketplace.py` — API routes

### P2-G: Skill Cross-Edition Sharing
- `SkillPromotion` model — promotion request with source/target edition
- `SkillMarketplace.promote()` — submit promotion request
- `SkillMarketplace.review_promotion()` — admin approve/reject with skill copy
- `SkillMarketplace.list_promotions()` — list promotion requests
- API: `POST /promote`, `POST /promotions/{id}/review`, `GET /promotions`

### New DB Models
- `SkillRating` (table 17) — per-user skill ratings
- `SkillSubscription` (table 18) — per-user skill subscriptions
- `SkillPromotion` (table 19) — cross-edition promotion requests

### New API Endpoints
- `GET /api/v1/marketplace/browse` — browse published skills
- `POST /api/v1/marketplace/subscribe` — subscribe to a skill
- `POST /api/v1/marketplace/unsubscribe/{skill_id}` — unsubscribe
- `GET /api/v1/marketplace/subscriptions` — list user subscriptions
- `POST /api/v1/marketplace/rate` — rate a skill
- `GET /api/v1/marketplace/{skill_id}/ratings` — get skill ratings
- `POST /api/v1/marketplace/promote` — promote skill across editions
- `POST /api/v1/marketplace/promotions/{id}/review` — review promotion
- `GET /api/v1/marketplace/promotions` — list promotions

---

## P3 — Advanced Features (Completed)

### P3-A: Voice/Vision Integration — Sprint 38 (v3.8.0)
- Cloud STT via httpx + OpenAI Whisper API compatible endpoint
- Chinese TTS (zh-CN-XiaoxiaoNeural) with asyncio fix
- LLM Vision API integration with OCR fallback (`ImageUnderstanding`)
- Vision API routes: `/api/v1/vision/analyze`, `/api/v1/vision/ocr`
- 16 new tests

### P3-B: Desktop Automation — Sprint 39 (v3.9.0)
- `FileSystemTool` (list/read/write within workspace, path traversal protection)
- `WindowManagerTool` (Windows/Linux/macOS cross-platform window listing)
- Desktop API routes: `/api/v1/desktop/files`, `/api/v1/desktop/windows`, `/api/v1/desktop/screenshot`
- RBAC `desktop` resource guard
- 20 new tests

### P3-C: Advanced Analytics Dashboard — Sprint 37 (v3.7.0)
- Real-time execution metrics (running tasks, completed/h, failed/h)
- LLM cost analytics (trend + provider breakdown) with persistent `LLMCostRecord` table
- Skill performance benchmarking (execution time + cost)
- Anomaly detection (failure spikes, cost spikes, skill degradation)
- 5 new API endpoints + 6 frontend ECharts charts + 30s auto-refresh
- 52 new tests

### P3-D: Multi-Agent Collaboration — Sprint 40 (v3.10.0)
- `AgentBus` message bus (directed/broadcast/async receive)
- Consensus voting (propose/vote/majority decision)
- `SubAgentRunner` real tool execution via tool_registry
- Agent management API (5 endpoints): status, messages, propose, vote, result
- 17 new tests

### P3-E: Plugin SDK — Sprint 41 (v3.11.0)
- `PluginBase` + `PluginManifest` + `PluginContext` SDK classes
- `PluginLoader` with importlib dynamic loading + hot-reload
- 8 Hook lifecycle (ON_LOAD/UNLOAD/TASK_CREATE/UPDATE/EXECUTE_START/END/SKILL_EXTRACT/CUSTOM)
- Sandboxed execution (workspace isolation, path traversal protection, file size limits)
- Plugin API (5 endpoints): list, discover, activate, deactivate, reload
- 23 new tests

### P3-F: Enterprise SSO & RBAC — Sprint 36 (v3.6.0)
- OIDC SSO with PKCE + nonce + JIT user provisioning
- RBAC: 4 roles, 52 permissions, 22 resources, TTL permission cache
- 22 route guards + RBAC management API (16 endpoints)
- Vue management UI + Alembic migration (4 tables)
- 104 new tests
