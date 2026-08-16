# Zcode Desktop Agent — 用户指南

> 版本: P3 (MVP 功能闭环)
> 更新: 2026-08-03
> 适用: Personal / Self-hosted Profile

## 1. 安装与首次启动

### 1.1 前置条件

- Windows 10 22H2+ / Ubuntu 22.04+ / macOS 13+
- WebView2 Runtime (Windows, 大多数 Win10 22H2 已预装)
- Python 3.12+ (随应用打包,无需单独安装)
- 磁盘空间: ≥ 500MB (应用) + 工作区

### 1.2 首次启动流程

1. 启动 Zcode Desktop Agent
2. 选择 Profile:
   - **Personal**: 单机本地运行,数据存本地
   - **Self-hosted**: 连接到自托管服务器
   - **Hybrid**: 本地+远程混合
3. 配置 LLM 模型:
   - BYOK: 填入 OpenAI/Anthropic/DeepSeek/Gemini API Key
   - 本地模型: 安装 Ollama,选择模型(推荐 qwen2.5:7b)
4. 设置工作区: 选择文件操作根目录
5. 完成初始化

### 1.3 Secret 安全

- API Key 存储在 OS 密钥环 (Windows Credential Manager / Linux Secret Service / macOS Keychain)
- 数据库中 **不存储** 明文密钥,只存 key_id + 掩码
- 日志中自动脱敏 (SECRET_KEY/API_KEY/Token → `***`)

## 2. 核心操作

### 2.1 创建任务

任务 = 一个目标 + 一组步骤。系统自动:
1. 规划步骤 (Plan)
2. 策略检查 (Policy): 低风险自动执行,高风险等待审批
3. 逐步执行,每步产生 Effect 记录
4. 完成后审计记录

### 2.2 审批队列

高风险操作 (file.delete, shell.execute, desktop.click) 会:
- 挂起执行,创建 ApprovalRequest
- 在审批队列显示: 工具名、参数、风险等级
- 需要 **非发起人** 投票批准
- 发起人不能自审

**审批 API**:
```
GET  /api/v1/gateway-approvals           查看待审批列表
GET  /api/v1/gateway-approvals/{id}       查看详情
POST /api/v1/gateway-approvals/{id}/vote  投票 (approve/reject)
POST /api/v1/gateway-approvals/{id}/resolve 检查 quorum 并决议
```

### 2.3 工作区安全

所有文件操作被限制在工作区根目录内:
- 路径遍历 (`../../../etc/passwd`) 被阻止
- 符号链接逃逸被检测
- Windows junction 被检测
- UNC 网络路径被阻止

### 2.4 下载安全

所有下载产物进入隔离区:
- MIME 嗅探 (魔法字节,不信 Content-Type)
- 文件大小限制 (默认 50MB)
- 可执行格式拦截 (ELF/PE/Mach-O/shell script)
- 被阻止的文件保留在隔离区,不进入工作区

## 3. 备份与恢复

### 3.1 创建备份

```powershell
$headers = @{ Authorization = "Bearer $env:ZCODE_ADMIN_TOKEN" }
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/v1/admin/backup' -Headers $headers
```

备份包含:
- SQLite 在线备份 API 生成的数据库快照
- 不包含工作区文件
- 当前实现不自动生成 SHA-256 清单,发布/事件流程需另行记录摘要

### 3.2 查看备份

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8000/api/v1/admin/backups' -Headers $headers
```

### 3.3 恢复备份

当前没有 `zcode backup restore` CLI。按 [Database Corruption Runbook](../runbooks/db-corruption.md) 停止服务、验证 SQLite、保留 `.pre-restore` 副本并离线恢复。

### 3.4 崩溃恢复

- SQLite WAL 降低崩溃损坏风险,但不能保证所有强制终止场景零数据丢失
- 重启前必须执行数据库完整性和 Alembic revision 检查

## 4. 浏览器隔离

每个任务使用独立的浏览器上下文:
- Cookie / localStorage 不跨任务共享
- 任务完成后自动清除存储
- 出站请求经过 SSRF 防护:
  - 阻止 loopback (127.0.0.1)
  - 阻止私网 (10.x / 172.16.x / 192.168.x)
  - 阻止云元数据端点 (169.254.169.254)
  - 支持 allowlist / denylist

## 5. 审计

所有操作记录在审计日志:
- 按时间 / actor / 动作过滤
- 包含完整执行链: Policy → Grant → Lease → Effect → Receipt
- Effect 状态: CONFIRMED / FAILED / UNKNOWN_OUTCOME
- UNKNOWN_OUTCOME 进入对账队列,需人工确认
