# 离线部署指南 (Offline Deployment)

> 版本: P3
> 更新: 2026-08-03
> 适用: 无外网环境 (air-gapped) 部署

## 1. 前置准备 (在有网环境完成)

### 1.1 下载安装包

在有网络的机器上:
```bash
# 下载最新 release (P4 阶段提供签名包)
# Windows: zcode-setup-{version}.msi
# Linux:   zcode-{version}.deb 或 .AppImage
# macOS:   zcode-{version}.dmg

# 下载本地模型 (如需)
ollama pull qwen2.5:7b
# 将模型文件导出
ollama export qwen2.5:7b > qwen2.5-7b.modelfile
```

### 1.2 下载 Python 依赖 (如自托管服务器)

```bash
# 在有网机器上下载所有 wheel
pip download -r requirements.txt -d /offline/packages/
pip download -r requirements-dev.txt -d /offline/packages/

# 打包
tar czf offline-deps.tar.gz /offline/
```

### 1.3 校验签名

```bash
# 验证安装包签名 (P4 阶段)
codesign --verify zcode-setup-{version}.msi    # Windows
dpkg-sig --verify zcode-{version}.deb           # Linux
codesign --verify --deep zcode-{version}.dmg    # macOS
```

## 2. 离线安装

### 2.1 Desktop Agent (Personal Profile)

1. 将安装包复制到目标机器 (U盘 / 内网传输)
2. 运行安装程序
3. 首次启动选择 "离线模式"
4. 配置本地模型 (从离线模型文件导入)

### 2.2 Self-hosted Server

```bash
# 1. 安装 Python 依赖
pip install --no-index --find-links=/offline/packages/ -r requirements.txt

# 2. 初始化数据库
alembic upgrade head
python scripts/init_db.py

# 3. 设置 SECRET_KEY
export SECRET_KEY="$(openssl rand -hex 32)"

# 4. 启动
uvicorn apps.api_server.main:app --host 0.0.0.0 --port 8000
```

### 2.3 企业静默安装

```bash
# Windows (MSI 静默安装)
msiexec /i zcode-setup-{version}.msi /quiet INSTALLDIR="C:\Program Files\Zcode" SECRET_KEY="<key>"

# Linux (deb)
sudo dpkg -i zcode-{version}.deb
sudo zcode configure --secret-key "<key>" --workspace "/opt/zcode/workspace"
```

## 3. 离线模型配置

### 3.1 导入 Ollama 模型

```bash
# 从离线文件导入
ollama create qwen2.5:7b -f qwen2.5-7b.modelfile

# 验证
ollama list
ollama run qwen2.5:7b "hello"
```

### 3.2 模型路由配置

编辑 `configs/app.yaml`:
```yaml
llm:
  providers:
    - name: "local-ollama"
      type: "ollama"
      url: "http://localhost:11434"
      model: "qwen2.5:7b"
      # 离线环境无 BYOK,只用本地模型
```

## 4. 离线更新

离线环境无法使用自动更新。更新流程:

1. 在有网机器下载新版本安装包
2. 校验签名
3. 复制到离线机器
4. 运行更新 (应用会自动备份当前版本)
5. 验证: 检查 schema 版本 + 运行健康检查

```bash
# 更新前备份
zcode backup create --notes "pre-update"

# 安装新版本 (覆盖安装)

# 验证
zcode doctor    # 诊断检查
alembic current # DB 版本
```

## 5. 离线环境限制

| 功能 | 离线可用 | 说明 |
|---|---|---|
| 本地模型推理 | ✅ | Ollama 本地运行 |
| 文件/Shell/浏览器工具 | ✅ | 完全本地 |
| 审批/审计 | ✅ | 完全本地 |
| BYOK (OpenAI/Claude) | ❌ | 需外网 |
| Web 搜索 | ❌ | 需外网 |
| 浏览器访问外部网站 | ❌ | 受 SSRF + 网络限制 |
| 自动更新 | ❌ | 手动离线更新 |
| 受控进化 (P7) | ✅ | 本地评估 + 人工晋升 |

## 6. 安全注意事项

- 离线环境的 SECRET_KEY 仍需安全分发 (不要写入安装脚本明文)
- 安装包签名验证是离线环境的安全基线 (防供应链注入)
- 本地模型同样需要审查 (模型文件本身可能含恶意内容)
- 备份介质需物理安全 (离线备份包含完整数据)
