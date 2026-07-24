# 复制到项目目录

当前运行环境中 `F:` 是未挂载的 USB 卷，因此团队包先生成在：

```text
C:\tmp\super-agent-self-agent-team
```

重新插入或挂载项目盘后，在 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File C:\tmp\super-agent-self-agent-team\COPY-TO-PROJECT.ps1
```

脚本默认复制到：

```text
F:\Agents\super-agent-self\.agent-team
```

脚本不会删除目标目录；目标已存在时默认拒绝覆盖。确认目标目录内容后，若确实需要覆盖，再显式运行：

```powershell
powershell -ExecutionPolicy Bypass -File C:\tmp\super-agent-self-agent-team\COPY-TO-PROJECT.ps1 -AllowOverwrite
```

复制完成后运行：

```powershell
powershell -ExecutionPolicy Bypass -File F:\Agents\super-agent-self\.agent-team\Validate-Team.ps1
```

然后让开发工具加载 `.agent-team\team.config.json`，默认入口为 `chief-orchestrator`。

