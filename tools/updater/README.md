# Updater & N-1 回退操作手册(P4 阻塞项 #5)

## 架构

```
构建机(有私钥)                    CDN                    客户端
  tauri build ──> app.exe + .sig ──┐
                                   ├─ /latest.json(签名 manifest)
  make_latest_json.py ────────────┘   /Zcode_1.0.1_x64-setup.exe
                                                          │
                                              updater 校验 pubkey(编译期内置)
                                              → 下载 → 校验 .sig → 双阶段安装
                                              → 断电安全(NSIS 事务回滚)
```

## 一次性设置(每把密钥只做一次)

```bash
bash tools/updater/keygen.sh
# 按提示:公钥进 tauri.conf.json plugins.updater.pubkey
#         私钥离线备份(丢失=永远无法再发更新)
```

## 发版流程

```bash
# 1. 构建机导出签名密钥
export TAURI_SIGNING_PRIVATE_KEY=$(cat ~/.tauri/zcode-updater.key)
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD='...'

# 2. 构建(tauri build 自动产出 updater bundle + .sig)
cd apps/desktop && npm run tauri build

# 3. 生成 latest.json
python tools/updater/make_latest_json.py \
  --version 1.0.1 --notes "..." \
  --url-base https://cdn.example.com/zcode \
  --installer ".../bundle/nsis/Zcode Desktop Agent_1.0.1_x64-setup.exe"

# 4. 上传 CDN:installer + .sig + latest.json(同批原子切换)
# 5. Gate Record 登记: 版本/sha256/pub_date/批准人
```

## 分阶段渠道(staged rollout)

CDN 目录即渠道,`latest.json` 切换即放量:

```
/zcode/internal/latest.json     # 0. 安装即入 internal 渠道
/zcode/invited/latest.json      # 1. 受邀用户
/zcode/stable-10pct/latest.json # 2. 10% → 50% → 100%(stable-10pct 等)
```

客户端渠道写在 `%LOCALAPPDATA%\zcode\channel`。放量决策记入
`docs/releases/<version>-rollout.md`(含观察窗口 SLO)。

## N-1 回退(原子回滚)

**原则**: N-1 安装包永久保留于 CDN(`_archive/` 目录),manifest
回退 = 把 N-1 的版本数据重新发布到当前渠道 `latest.json`。客户端
updater 见"低版本"默认不降级 → 回退需带 `allow-downgrade` 通道标记
(latest.json notes 前缀 `ROLLBACK:`),客户端识别后允许降级安装。

```powershell
# 回退脚本(构建机/发布机,PowerShell):
$failed = "1.0.1"; $good = "1.0.0"
Copy-Item "cdn:\zcode\_archive\latest-$good.json" "cdn:\zcode\stable\latest.json"
# 编辑该 latest.json: notes 改为 "ROLLBACK: $failed has <issue>, reverting"
# 客户端下次检查(默认每 24h 或启动时)自动回退
```

**回退演练(必做,进 artifacts)**:
1. 装 1.0.0 → 升 1.0.1 → 发 ROLLBACK manifest → 客户端回到 1.0.0
2. 断电测试: 更新安装中拔电 → 重启后应用可启动(旧版或续装,无半迁移 DB)

## 安全属性(已内建)

- manifest/产物被篡改 → updater pubkey 校验失败 → 拒绝安装
- 渠道错误 → 交叉渠道 URL 无效
- 版本回放(重发旧 latest.json)→ ROLLBACK 标记外的旧版本被拒降级
- NSIS 双阶段 + 事务:断电后旧版完整或新版完整,不存在中间态
