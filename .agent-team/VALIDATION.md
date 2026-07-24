# 配置验证

Windows PowerShell 5默认可能把无BOM UTF-8文件按本地代码页读取。本包的验证脚本固定使用`-Encoding UTF8`，避免中文Prompt或JSON描述被误解析。

在团队包目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\Validate-Team.ps1
```

如果团队包已经放到项目的`.agent-team`目录，也可以在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\.agent-team\Validate-Team.ps1
```

脚本检查：

- `team.config.json`和`runtime-policy.json`是有效UTF-8 JSON。
- Agent ID和Prompt文件映射唯一。
- entry Agent存在。
- 14份Prompt全部存在并具有最低深度。
- 每份Prompt包含身份、非职责、完成定义和输出协议。
- 不存在省略实现的占位内容。
- 路由中的Implementer和Reviewer都存在且不存在自审。
- 所有共享协议文件存在。
- 最大并发不超过4。
- R3和生产操作必须经过人工批准。

验证通过只表示Agent团队配置内部一致，不表示项目实现、架构或生产环境已经通过发布Gate。

