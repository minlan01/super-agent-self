# Myself-Agent Optimization Plan — Sprint 42-45

> Status: PENDING APPROVAL
> Scope: Critical bug fixes + Architecture improvements + Code quality
> Estimated effort: 4 Sprints (11 days)
> Execution mode: Autopilot + Ultrawork (parallel agents)

---

## Sprint 42: CRITICAL Fixes (2 days)

### T42-1. Sync pyproject.toml version to 3.11.0
- **File**: `pyproject.toml:7`
- **Change**: `version = "3.4.0"` → `version = "3.11.0"`
- **Verify**: `grep version pyproject.toml` matches `packages/agent_core/version.py`
- **Model**: haiku (trivial)

### T42-2. Fix RBAC route wrong get_db import
- **File**: `apps/api_server/routes/rbac.py:26`
- **Change**: `from packages.db.session import get_db` → `from apps.api_server.dependencies import get_db`
- **Verify**: All 31 route modules import get_db from same source; run rbac tests
- **Model**: haiku (trivial)

### T42-3. Consolidate Secret Key to single source
- **Files**:
  - `apps/api_server/dependencies.py:69` — remove `AGENT_SECRET_KEY`, use `get_settings().security.secret_key`
  - `packages/config.py:93` — keep as single source
  - `apps/api_server/dependencies.py` — update TokenIssuer to use `settings.security.secret_key`
- **Verify**: grep confirms no `AGENT_SECRET_KEY` references remain; auth tests pass
- **Model**: sonnet (multi-file, needs care)

### T42-4. Fix asyncio.run() in running event loops (4 locations)
- **Files**:
  - `packages/agent_core/orchestrator.py:42` — use `asyncio.ensure_future` in all paths
  - `packages/voice/voice_service.py:184,186` — restructure TTS to pure async
  - `packages/mcp/mcp_tool_adapter.py:42` — make adapter async, caller awaits
  - `packages/cron/scheduler.py:137` — use `loop.run_until_complete()` with loop check
- **Pattern**: Replace `asyncio.run()` with:
  ```python
  try:
      loop = asyncio.get_event_loop()
      if loop.is_running():
          asyncio.ensure_future(coro)
      else:
          loop.run_until_complete(coro)
  except RuntimeError:
      asyncio.run(coro)
  ```
- **Verify**: Unit tests pass; no RuntimeError in event loop
- **Model**: sonnet (needs async understanding)

### T42-5. Add rollback to get_db() session management
- **File**: `packages/db/session.py:72-78`
- **Change**: Add `db.commit()` on success, `db.rollback()` on exception
- **Impact**: This is the foundation for Sprint 43's transaction cleanup
- **Verify**: All tests pass; manual test with intentional error shows rollback
- **Model**: haiku (small, critical)

**Sprint 42 Parallelization**:
```
T42-1 ─┐
T42-2 ─┤ (all independent, run in parallel)
T42-3 ─┤
T42-5 ─┘
T42-4   (independent, separate agent)
```

---

## Sprint 43: P0 Fixes (3 days)

### T43-1. Remove create_all() from production startup
- **File**: `apps/api_server/main.py:47`
- **Change**: Remove `Base.metadata.create_all(bind=engine)` from lifespan
- **Alternative**: Add `--init-db` CLI flag for first-time setup only
- **Also fix**: `alembic.ini` hardcoded path `sqlite:///data/agent.db` → use env var
- **Verify**: Fresh DB works with `alembic upgrade head`; app starts without create_all
- **Model**: sonnet

### T43-2. Unify SSO token exchange (remove token from redirect URL)
- **File**: `apps/api_server/routes/auth.py:154`
- **Change**: Generate one-time authorization code → redirect with code → frontend POSTs code to exchange endpoint
- **New endpoint**: `POST /api/v1/auth/sso/token` — accepts code, returns token
- **Security**: Code expires in 60s, single-use, stored in memory/dict
- **Verify**: SSO flow integration test
- **Model**: opus (security-sensitive, new endpoint)

### T43-3. Cache get_settings() with @lru_cache
- **File**: `packages/config.py:67`
- **Change**: Add `@functools.lru_cache(maxsize=1)` to `get_settings()`
- **Consideration**: Config changes require process restart (acceptable)
- **Also**: Add `clear_settings_cache()` for testing
- **Verify**: Performance benchmark; tests pass
- **Model**: haiku (trivial)

### T43-4. Standardize exception handling in critical paths
- **Files** (top priority):
  - `packages/auth/auth_service.py:84` — narrow to `json.JSONDecodeError, ValueError, binascii.Error`
  - `apps/api_server/main.py:63` — change `warning` → `error` for RBAC seed failure
  - `packages/agent_core/orchestrator.py:43` — change `debug` → `warning` for plugin hooks
  - `packages/notification/ws_broadcaster.py:37,45` — add `logger.exception()` instead of silent
- **Pattern**: Replace broad `except Exception:` with specific exceptions in auth/security paths
- **Verify**: Tests pass; intentional errors produce proper logs
- **Model**: sonnet

### T43-5. Migrate db.commit() out of repositories into get_db() transaction boundary
- **Scope**: Phase 1 — Repositories only (13 files)
- **Change**: Replace `db.commit()` with `db.flush()` in all repository methods
- **Rely on**: Sprint 42's T42-5 `get_db()` auto-commit for transaction boundary
- **Files**: All 13 files in `packages/db/repositories/`
- **Verify**: Run full test suite
- **Model**: sonnet (many files, mechanical change)

### T43-6. Migrate db.commit() out of services
- **Scope**: Phase 2 — Services (depends on T43-5)
- **Files**:
  - `packages/skills/skill_registry.py` (7 commits)
  - `packages/skills/marketplace.py` (9 commits)
  - `packages/notification/notification_service.py` (1 commit)
  - `packages/memory/memory_service.py` (1 commit)
  - `packages/auth/rbac.py` (1 commit)
  - `packages/personal_context/reminder_service.py` (2 commits)
  - `packages/llm_gateway/cost_tracker.py` (1 commit)
- **Change**: Replace `db.commit()` with `db.flush()` (transaction managed by get_db)
- **Verify**: Full test suite passes
- **Model**: sonnet

**Sprint 43 Parallelization**:
```
T43-1 ─┐
T43-3 ─┤ (independent)
T43-4 ─┘
T43-5 ──→ T43-6  (sequential: repos first, then services)
T43-2   (independent, security work)
```

---

## Sprint 44: P1 Fixes (3 days)

### T44-1. Unify API response format — Add response_model to all routes
- **Scope**: Routes without `response_model` (~50 endpoints)
- **Files**:
  - `routes/analytics.py` (12 endpoints)
  - `routes/admin.py` (6 endpoints)
  - `routes/agents.py` (5 endpoints)
  - `routes/personal.py` (7 endpoints)
  - `routes/webhooks.py` (4 endpoints)
  - `routes/marketplace.py` (10 endpoints)
  - `routes/plugins.py` (5 endpoints)
  - `routes/search.py` (1 endpoint)
- **Pattern**: Create generic `ApiResponse[T]` Pydantic model, apply to all endpoints
- **Verify**: `/docs` shows all response schemas; tests pass
- **Model**: sonnet (mechanical, many files)

### T44-2. Deduplicate WebSocket code
- **File**: `apps/api_server/routes/ws.py` (675 lines → 3 files)
- **Split into**:
  - `ws/connection_managers.py` — single generic `ConnectionManager` class
  - `ws/ws_auth.py` — shared WS auth decorator
  - `ws/ws_routes.py` — 3 WS endpoints using shared managers/auth
- **Also**: Extract shared admin user factory to `dependencies.py`
- **Verify**: All WS tests pass; ws routes work via TestClient
- **Model**: sonnet (refactoring)

### T44-3. Unify thread-DB pattern
- **Files**:
  - `routes/chat.py:21-31` — `_thread_db_call`
  - `routes/analytics.py:31-46` — `_thread_query`
  - `routes/tasks.py:113-163` — inline closures
- **Target**: `packages/db/session.py` — add `run_in_thread(func, *args)` utility
- **Verify**: All route tests pass; grep confirms no more inline patterns
- **Model**: sonnet

### T44-4. Add RBAC to GraphQL resolvers
- **File**: `packages/graphql/resolvers.py`
- **Change**: Pass user context to resolvers, check permissions per query type
- **Also**: Replace manual `SessionLocal()` with `get_db()` injection
- **Verify**: GraphQL queries return 403 without proper permissions
- **Model**: sonnet (needs GraphQL + RBAC understanding)

**Sprint 44 Parallelization**:
```
T44-1 ─┐
T44-2 ─┤ (all independent)
T44-3 ─┤
T44-4 ─┘
```

---

## Sprint 45: P2 Improvements (3 days)

### T45-1. Fix N+1 query in task detail
- **File**: `routes/tasks.py:90-100`
- **Change**: Remove redundant `TaskRepository.get_steps()` call (already joinedloaded)
- **Verify**: SQL log shows single query
- **Model**: haiku

### T45-2. Optimize analytics queries
- **File**: `routes/analytics.py:513-610`
- **Change**: Consolidate 8 sequential scalar queries into 2-3 CTEs
- **Verify**: Analytics page loads faster; test data returns same results
- **Model**: sonnet

### T45-3. Optimize backup list (skip integrity check on list)
- **File**: `packages/admin/backup_service.py:170`
- **Change**: Move `_validate_sqlite_file` to on-demand only (separate endpoint)
- **Verify**: `list_backups` is fast with many backups
- **Model**: haiku

### T45-4. Add RBAC cache eviction
- **File**: `packages/auth/rbac.py:18-43`
- **Change**: Add periodic pruning of expired cache entries; cap dict size
- **Verify**: Cache doesn't grow unbounded under load
- **Model**: haiku

### T45-5. Fix E2E test env var leakage
- **File**: `tests/conftest.py`
- **Change**: Add `SECRET_KEY` to `_E2E_ENV_KEYS` tuple
- **Also**: Move module-level env sets into fixtures
- **Verify**: Test order doesn't affect results
- **Model**: haiku

### T45-6. Enhance CI pipeline
- **File**: `.github/workflows/ci.yml`
- **Add**:
  - `pytest --cov=packages --cov-report=xml` + coverage upload
  - `alembic check` (detect model/migration drift)
  - `pytest -m unit` / `pytest -m integration` marker runs
- **Verify**: CI runs all checks
- **Model**: sonnet

### T45-7. Add missing route integration tests
- **New files**:
  - `tests/integration/test_webhooks_api.py`
  - `tests/integration/test_marketplace_api.py`
  - `tests/integration/test_personal_api.py`
  - `tests/integration/test_files_api.py`
  - `tests/integration/test_agents_api.py`
- **Pattern**: Follow existing integration test pattern (conftest app_and_client)
- **Verify**: All new tests pass; coverage increases
- **Model**: sonnet (per file, parallel)

### T45-8. Unify structured logging
- **File**: `packages/observability/structured_logger.py`
- **Change**: Configure structlog as global logger; update `logging.getLogger()` calls to use structlog
- **Scope**: Phase 1 — core packages (auth, executor, planner, policy)
- **Verify**: Log output is JSON structured; all tests pass
- **Model**: sonnet

### T45-9. Add pagination utility
- **New file**: `packages/db/pagination.py`
- **Create**: `paginate(query, page, size) -> PaginatedResult` generic utility
- **Apply**: To `notifications`, `marketplace`, `tasks` list endpoints
- **Verify**: Endpoints return paginated results
- **Model**: sonnet

**Sprint 45 Parallelization**:
```
T45-1 ─┐
T45-3 ─┤
T45-4 ─┤ (all independent, haiku-level)
T45-5 ─┘
T45-2 ─┐
T45-6 ─┤ (independent, sonnet-level)
T45-8 ─┤
T45-9 ─┘
T45-7   (independent, 5 parallel agents)
```

---

## Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| T42-5 get_db() commit breaks existing flows | Medium | High | Run full test suite; keep flush in repos |
| T43-5/6 commit→flush migration | Low | High | Mechanical change; test per file |
| T44-2 WS refactor breaks WS connections | Medium | Medium | Keep same public API; integration test |
| T43-2 SSO code exchange is new endpoint | Low | Medium | Feature-flag behind SSO enabled check |
| T44-1 response_model breaks existing clients | Low | High | Response shape stays compatible |

## Rollback Strategy

Each Sprint is a separate commit. If a Sprint introduces regressions:
1. Revert the Sprint commit
2. Fix the specific issue
3. Re-run tests
4. Re-commit

## Success Criteria

- [ ] `pyproject.toml` version matches `version.py`
- [ ] All 31 routes import `get_db` from same source
- [ ] Single `SECRET_KEY` source (no `AGENT_SECRET_KEY`)
- [ ] No `asyncio.run()` in async context
- [ ] `get_db()` auto-commits/rollbacks
- [ ] No `db.commit()` in repositories or services
- [ ] All routes have `response_model`
- [ ] WS code deduplicated
- [ ] All tests pass (2100+)
- [ ] CI runs coverage + alembic check
