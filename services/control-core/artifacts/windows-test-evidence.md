# P3 Windows 验收矩阵执行证据

- 执行日期: 2026-08-08
- 执行环境: Windows 11 (build 26200), Python 3.12.10
- venv: .venv-win (pywin32 309, Pillow 11.3, structlog 24.4)
- Git baseline: 30a9dcd → 多个 P3 commit

## 自动测试结果

### P3.0 门禁测试 (no-bypass + unknown-outcome)

```
tests/unit/test_no_bypass.py: 7 passed
tests/unit/test_unknown_outcome.py: 4 passed
Total: 11 passed
```

### P2 既有安全链测试 (orchestrator + gateway)

```
tests/test_orchestrator.py: 5 passed
tests/test_tool_gateway.py: 10 passed
Total: 15 passed
```

### Windows P1 合约测试

```
packages/platform/windows/tests/test_contract_integration.py: 8 passed, 4 skipped
packages/platform/windows/tests/test_windows_api.py: 20 passed
packages/platform/windows/tests/test_wire.py: 6 passed
Total: 34 passed, 4 skipped
(skipped: "non-Windows fail closed" tests — expected on Windows)
```

### P3.9 隔离边界测试

```
packages/platform/windows/tests/test_isolation.py: 15 passed, 1 skipped
(env filtering, secret broker, egress control, ACL, fail-closed)
```

### P3.10 参数化执行 + ConPTY 测试

```
packages/platform/windows/tests/test_process_conpty.py: 16 passed
(request validation, security checks, ConPTY contract)
```

### P3.11 UIA + P3.12 WGC 测试

```
packages/platform/windows/tests/test_desktop_capture.py: 16 passed
(stale detection, classification, artifact, capability)
```

### 合计

| 套件 | Collected | Passed | Failed | Skipped |
|------|-----------|--------|--------|---------|
| no-bypass | 7 | 7 | 0 | 0 |
| unknown-outcome | 4 | 4 | 0 | 0 |
| orchestrator | 5 | 5 | 0 | 0 |
| tool-gateway | 10 | 10 | 0 | 0 |
| contract-integration | 12 | 8 | 0 | 4 |
| windows-api | 20 | 20 | 0 | 0 |
| wire | 6 | 6 | 0 | 0 |
| isolation | 16 | 15 | 0 | 1 |
| process-conpty | 16 | 16 | 0 | 0 |
| desktop-capture | 16 | 16 | 0 | 0 |
| **合计** | **112** | **107** | **0** | **5** |

## 全量收集

```
2476 tests collected (includes app tests beyond P3 scope)
```

## 人工验收清单 (尚未执行)

以下项目需要人工在真机环境执行：

- [ ] Windows 10 22H2 标准用户运行
- [ ] Windows 11 标准用户 + 管理员分别运行
- [ ] 100/125/150/200% DPI 测试
- [ ] 多屏、负坐标、旋转、热插拔
- [ ] Win+L 锁屏测试
- [ ] UAC secure desktop 测试
- [ ] 第二普通账户 Named Pipe 拒绝证据
- [ ] ConPTY 中文输入、resize、Ctrl-C、断连回收
- [ ] WGC 遮挡/最小化/DirectX/Electron
- [ ] Runner 不能读取 Control DB
- [ ] Runner 不能访问工作区外文件
- [ ] Runner 不能访问未授权网络
