# wizard.db 导出报告（2026-07-21）

## 结果

`more_agents/unified-admin/server/wizard.db` **不存在**。

可能原因：
- 该数据库在 unified-admin 首次启动 server 后才创建（better-sqlite3 懒加载）
- 当前是 vendor 时刻，server 从未启动过

## 后续处置（D 阶段 ETL 时）

由于 unified-admin/server/ 已在 S.4 vendor 时被排除，且 wizard.db 不存在，
**无需做 wizard.db → control-core 数据迁移**（G-13 缺口的"数据迁移"部分自动消解）。

如果将来 P3 阶段需要恢复某些 scenarios/tasks 历史数据，需先在原 unified-admin 仓
启动一次 server 让 wizard.db 生成，再 ETL。
