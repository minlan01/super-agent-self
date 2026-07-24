# 首次启用团队：规范基线收敛 Sprint

根据当前项目文档复核结果，团队首次运行不应直接新增功能。应先完成一次规范基线收敛，清除会让不同Agent实现不同真相的P0/P1矛盾。

## Sprint结果

形成一套唯一、可实现、可测试的生产候选规范，并让Interface、schema、UserStory、安全设计、部署设计和测试矩阵一致。完成不等于直接生产上线，后续仍需真实实现和Gate验证。

## 工作包

### SAS-BASE-01：建立规范源和baseline

- Owner：Chief Orchestrator
- Reviewer：Independent Release Reviewer
- 内容：记录五份核心文档、ADR、代码、schema和测试的revision/hash；识别生成副本；定义规范源优先级。
- 通过：每个结论可追溯到唯一版本，报告行数、hash和校验输出准确。

### SAS-BASE-02：收敛唯一执行链

- Owner：Architecture Governor
- 协作：Execution Consistency Engineer
- Reviewer：Security Governor、Test Automation Engineer、Independent Release Reviewer
- 内容：删除WorkerBroker直调ToolGateway旁路；冻结ExecutionControl、WorkerBroker、EffectJournal、ToolGateway和Adapter的Interface与所有权。
- 通过：全仓搜索只剩一条规范链，状态Owner无冲突。

### SAS-BASE-03：统一未知Effect恢复语义

- Owner：Product & Domain Lead
- 协作：Execution Consistency Engineer
- Reviewer：Architecture Governor、Test Automation Engineer
- 内容：删除“无Receipt即安全重试”和旧`ambiguous` AC；定义unknown、reconciliation和人工处置。
- 通过：UserStory、状态机、伪代码和测试矩阵表达同一结果。

### SAS-BASE-04：闭合M9 Interface与schema

- Owner：Data & Migration Engineer
- 协作：Architecture Governor、Execution Consistency Engineer
- Reviewer：Test Automation Engineer、Independent Release Reviewer
- 内容：补齐dispatch fencing、AuthorizationAttempt security/supply-chain digest和Worker身份；修正授权依据枚举和状态约束。
- 通过：Interface/schema一致性矩阵无P0/P1，数据库可拒绝非法记录。

### SAS-BASE-05：重构Grant与密钥域

- Owner：Security Governor
- 协作：Backend Engineer、Platform & SRE Engineer
- Reviewer：Security Validation Engineer、Independent Release Reviewer
- 内容：采用opaque handle或GrantIssuer独占私钥；Adapter不可签发；Grant、Audit及其他用途密钥分域。
- 通过：模拟Adapter失陷不能产生新Grant或伪造Audit。

### SAS-BASE-06：闭合Approval模型

- Owner：Product & Domain Lead
- 协作：Architecture Governor、Security Governor、Backend Engineer、Frontend Engineer
- Reviewer：Security Validation Engineer、Test Automation Engineer
- 内容：不可变Request/Vote/Resolution/Invalidation、禁止自审、服务端身份、上下文digest绑定、事务性唯一ResumeCommand，删除公开resume。
- 通过：自审、重复投票、上下文变化和直接resume测试全部拒绝。

### SAS-BASE-07：闭合tenant与Artifact安全

- Owner：Security Governor
- 协作：Data & Migration Engineer、Backend Engineer
- Reviewer：Security Validation Engineer
- 内容：RLS或tenant-qualified约束、ExternalReference workspace唯一性、跨存储scope matrix、Artifact quarantine与完整性。
- 通过：跨租户和恶意Artifact矩阵零绕过。

### SAS-BASE-08：重写cutover与rollback

- Owner：Data & Migration Engineer
- 协作：Platform & SRE Engineer、Observability & Incident Engineer
- Reviewer：Architecture Governor、Test Automation Engineer、Independent Release Reviewer
- 内容：drain、数据库硬freeze、旧连接/事务终止、final delta、校验、write epoch、cutover、观察窗口和目标写入后的rollback。
- 通过：演练中冻结前后并发写不丢失，旧实例无法写，校验失败自动中止。

### SAS-BASE-09：建立语义验证Gate

- Owner：Test Automation Engineer
- 协作：Security Validation Engineer、Observability & Incident Engineer
- Reviewer：Independent Release Reviewer
- 内容：把Effect、Grant、Approval、tenant、Artifact、cutover和恢复不变量变成自动测试与故障注入；重新定义模板校验的证据范围。
- 通过：所有P0场景有行为测试，模板检查不再被描述为生产正确性证明。

### SAS-BASE-10：生成候选基线报告

- Owner：Docs & Release Engineer
- Reviewer：Architecture Governor、Security Governor、Independent Release Reviewer
- 内容：同步五份文档，记录diff、hash、ADR、真实命令和未运行检查；准确区分已设计、已实现、已验证、延期和禁用。
- 通过：Independent Reviewer找不到双规范路径或未披露P0/P1，结论不超过实际证据。

## 执行顺序

```text
BASE-01
  -> BASE-02 + BASE-03
  -> BASE-04 + BASE-05 + BASE-06
  -> BASE-07 + BASE-08
  -> BASE-09
  -> BASE-10
```

只有没有写路径冲突的工作包可以并行，最大并发4。BASE-02冻结核心Interface前，不允许实施新的外部副作用功能。

