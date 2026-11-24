# MovieHub 项目总进度与交付清单

> **当前基线：2026-11-24**  
> 仓库：`daxiguaya/MovieHub`  
> 工作分支：`phase4/database-foundation`  
> 当前阶段：**部署前收尾（Pre-deployment hardening）**  
> 整体进度估算：**约 75%**。这是项目交付进度估算，不是测试通过率。

## 一句话结论

MovieHub 的独立 SQLite 数据库基础、主要后端 API、React 前端核心流程、榜单采集/导入链路、容器构建和备份恢复工具已经实现，并在 GitHub Actions 的隔离环境中验证。**项目尚未部署，MovieHub 正式数据库尚未创建，也没有 NAS 生产实例。** 当前重点是把首发数据内容补到可用程度、完成界面/使用体验验收、补齐部署前操作验证，然后再单独审批 NAS 部署。

## 重要概念校正

- MovieHub 是新项目，尚未部署，因此**不存在 MovieHub 自己的正式源库或正式业务数据库**。
- MovieHub 的数据库由项目自己的显式初始化命令创建；不依赖某个已经存在的 MovieHub 数据库。
- Douban Scout 只是一个**可选的外部只读元数据来源/导入适配器**。Scout 全库审计不是当前数据库重构、初始化或首发部署的前置条件。
- 当前已经使用真实采集的豆瓣 2025 年度榜单数据，在 GitHub Actions 临时数据库中完成真实导入演练。这不是 Scout 全库导入，也不是生产数据库。
- 未来是否启用 Scout、从哪里提供其一致性只读副本、是否导入其元数据，应在需要时单独决定；不得把“等待 Scout 源库”写成 MovieHub 当前项目阻塞项。

## 已完成的工作

### A. 产品范围与架构
- [x] 明确首发路径：榜单发现 → 影片详情 → Xiaoya 搜索跳转。
- [x] 明确榜单、搜索/筛选、详情、海报、收藏、历史榜单和排名变化对比等首发功能。
- [x] 明确不负责下载、播放和媒体库管理；继续由 Xiaoya、Jellyfin、SmartStrm 承担各自职责。
- [x] 采用 React + TypeScript + Vite 前端、FastAPI 后端、独立 SQLite 数据库；不引入 Redis、MySQL、Elasticsearch 等额外基础设施。

### B. 数据库与后端
- [x] 独立 SQLite schema（11 张核心表）、ORM/schema 一致性校验、内部 MovieHub ID 关系。
- [x] 显式空库初始化、schema 版本检查、迁移备份、完整性/外键校验和失败回滚。
- [x] 缺失数据库时 API 返回明确 503，不会在应用启动或请求过程中偷偷创建数据库。
- [x] 榜单快照按榜单/日期隔离，支持历史快照、同日替换、排名比较和批量原子导入。
- [x] 影片搜索/筛选、详情、海报、收藏、导入状态等主要 API。
- [x] Scout 只读导入适配器已实现：增量/全量、500 条批次、记录级 SAVEPOINT、收据/检查点、重试与崩溃恢复；这是可选数据源适配能力，不代表当前存在 MovieHub 正式库。
- [x] 输入校验、身份冲突、媒体类型冲突、年份/评分/整数边界、导入目录路径与符号链接安全等质量闸门。
- [x] 海报抓取 SSRF 防护：HTTPS CDN 白名单、DNS 地址校验、逐跳重定向校验、响应大小/MIME/文件签名限制。

### C. 榜单采集与真实数据
- [x] 豆瓣 Top 250、热门/高分榜单的一次性采集器，含 robots.txt、速率限制和失败关闭策略。
- [x] 豆瓣官方 2025 年度四类榜单采集器；电影与剧集分开，保留真实排名，不补造缺失名次。
- [x] 四份 JSON 通过导入预检，采集产物作为 GitHub Actions artifact 保存，没有把抓取数据提交进 Git。
- [x] 对实际年度榜单 artifact 完成独立结构审查：4 个榜单共 38 条，Douban ID 38/38 非空且跨榜单无重复，排名连续。
- [x] **真实数据导入演练已完成**：在 GitHub Actions 临时新建 MovieHub SQLite 数据库，调用正式年度批量导入服务，导入 4 个榜单、38 部影片、38 条榜单项；`PRAGMA integrity_check=ok`，外键错误 0，排名连续。
- [ ] 扩充/丰富首发可用数据：目前年度采集结果只有 38 条且元数据字段稀疏（导演 38/38，其余年份、评分人数、演员、类型、地区、海报、简介等字段在该 artifact 中均未提供）。需要有来源依据的详情补全或更多榜单数据，不能从榜单年份推断影片年份，也不能伪造字段。
- [ ] 验收首发榜单组合、数据新鲜度和空数据/缺失字段时的前端呈现。
- [ ] 2026 年度榜单只在官方分类和真实数据发布并核实后再增加；不提前放空占位。
- [ ] 是否定时刷新仍待决定；当前采集器是手动/一次性运行，不是后台自动任务。

### D. 前端与用户流程
- [x] React/TypeScript/Vite 前端、首页发现、榜单页、历史日期选择和分页。
- [x] 搜索筛选：关键词、电影/剧集、评分、年份、类型/地区等条件。
- [x] 详情页、海报展示、豆瓣链接和 Xiaoya 跳转（标题 URL 编码）。
- [x] 收藏列表、添加/移除和备注交互。
- [x] 历史榜单排名变化展示。
- [x] 5 项前端回归测试和 4 项 Playwright Chromium E2E。
- [ ] 对真实数据进行完整视觉 QA 和交互验收；重点检查空值、长标题、海报失败、分页、移动端布局和异常提示。
- [ ] 对实际 Xiaoya URL 与反向代理路径做最终联调；代码中的跳转逻辑已测试，但尚未在 NAS/NPM 环境验收。

### E. 部署、运维和安全
- [x] 后端和前端 Dockerfile、Compose 服务定义。
- [x] 非 root 容器、只读根文件系统、能力收缩、no-new-privileges、资源/PID 限制和独立持久化卷。
- [x] Compose 不直接发布 NAS/LAN 服务端口；后端只接入预期的内部网络。
- [x] 显式一次性数据库初始化流程；容器启动不自动建库或迁移。
- [x] SQLite 在线备份、SHA-256 manifest、保留策略、校验恢复、恢复前回滚副本。
- [x] 健康检查与 readiness、配置模板、部署/备份恢复/导入 runbook。
- [ ] 目标 NAS 上的目录权限、Docker 网络、资源占用和实际性能验证。
- [ ] NPM 反向代理、HTTPS、API key 服务端注入、前端路径和 Xiaoya 跳转的实际联调。
- [ ] 在隔离/预生产目录完成首次初始化、真实榜单导入、备份、恢复和容器重建演练。
- [ ] 完成 NAS 部署检查清单和回滚方案评审。

## 真实年度数据浏览器验收（已通过，2026-11-24）

- [x] Playwright 真实年度数据用户旅程：遍历四个 2025 年度榜单，核对 8/10/10/10 条目数，打开真实影片详情，再用真实标题执行搜索。
- [x] 独立 GitHub Actions job 下载已留存的官方年度榜单 artifact，在 runner 临时目录初始化独立 MovieHub SQLite，导入四份真实快照，启动真实 FastAPI 并运行 Chromium 浏览器用例。
- [x] GitHub Actions run [#45315898896](https://github.com/daxiguaya/MovieHub/actions/runs/45315898896)：real-annual-data-browser-e2e **success**，所有 14 个步骤成功。
- [x] Backend 和 Frontend job 同次运行均 success；独立真实数据链路完成导入、API readiness、榜单页、影片详情和搜索验证。
- [x] 修复测试隔离：真实年度浏览器用例现在仅在设置 `MOVIEHUB_REAL_ANNUAL_E2E=1` 的专用 CI job 执行；普通 fixture E2E 不再误跑依赖年度 artifact 的场景。
- [x] 普通 fixture E2E 在隔离修复提交后重新跑绿；GitHub Actions run #45317668299 的 fixture E2E 已 success。
- [x] 全流程仅使用 GitHub runner 临时数据库，不连接 NAS、不读取 Scout、不创建生产数据库，也不改动 NPM 或 NAS 服务。

### 最新真实年度数据浏览器验收
- [GitHub Actions run #45315898896](https://github.com/daxiguaya/MovieHub/actions/runs/45315898896)，提交 `e1c85ae`。
- Backend：success；Frontend：success；real-annual-data-browser-e2e：success。
- 真实数据 job 下载官方 artifact、创建临时 SQLite、导入 4 榜 38 条数据、启动 FastAPI，并通过四榜页面/真实详情/真实标题搜索的 Chromium 验收。
- 同次运行的通用 `frontend-e2e` 曾失败，原因是它把只适用于真实年度 artifact 的场景也跑在仅含《星际穿越》fixture 的数据库上，导致预期 8 条但 fixture 数据库没有该榜单。这不是产品代码故障，而是测试范围隔离错误；已通过环境标志将该场景限定在专用 job，等待修复后的通用 E2E 复验。
- 因此：真实年度数据浏览器链路已通过；普通 fixture E2E 的复验仍是待办，不能将整个 workflow 记为全绿。

## 首发真实数据扩充与临时库导入（已通过，2026-11-24）

- [GitHub Actions run #45320596952](https://github.com/daxiguaya/MovieHub/actions/runs/45320596952)：Backend、Frontend、普通 fixture E2E、first-launch-data-collection 全部 success。
- 数据来源：新采集豆瓣 Top 250（2026-11-24，250 条）+ 已留存并验证的豆瓣官方 2025 年度四榜（38 条）。
- 合并导入结果：**5 个快照 / 288 条榜单项 / 288 个唯一影片 / 跨榜重复 0**。Top 250 与四个年度榜单均已写入 GitHub runner 临时 SQLite。
- 完整性：PRAGMA integrity_check=ok，PRAGMA foreign_key_check 0 条错误。
- Top 250 字段覆盖率：年份 248/250（99.2%）、评分 250/250（100%）、原名 223/250（89.2%）、类型/地区 248/250（99.2%）、海报 250/250（100%）；评价人数、导演、演员、简介目前 0%。缺失字段保持缺失，没有编造。
- artifact：moviehub-first-launch-douban（5 个 JSON 文件，保留 14 天），可供后续浏览器验收复用。
- robots 限制：热门/高分榜所用网页接口被豆瓣 robots.txt 禁止，采集器停止并已从首发工作流移除；不绕过访问限制。
- 本次 CI 中性能 benchmark、年度重新采集和旧年度数据 rehearsal 均 skipped，不计为本轮通过。

## 当前 CI 验证基线

### 最新分支 CI
- [GitHub Actions run #45312384087](https://github.com/daxiguaya/MovieHub/actions/runs/45312384087)，提交 `04354ed`，整体 success。
- Backend：**247 passed，4 skipped，1 warning**。
- Frontend：**5 passed**，TypeScript 检查、Vite production build 和前端镜像构建成功。
- Chromium E2E：**4 passed**。
- Compose 校验和后端镜像构建成功。
- 本次文档提交触发的 real-data rehearsal、年度采集和性能 benchmark job 均为 **skipped**，不能算作本次运行通过。

### 最近一次真实年度数据导入演练
- [GitHub Actions run #45312215353](https://github.com/daxiguaya/MovieHub/actions/runs/45312215353)。
- real-annual-data-import-rehearsal：success；独立验证 4 charts / 38 movies / 38 chart items / 0 FK errors / integrity ok。
- 同次运行 backend 247 passed、frontend 5 passed、E2E 4 passed。
- 年度采集和性能 benchmark job 在该次运行中 skipped；性能基准来自此前专门启用的 benchmark run，不能混算为本次执行。

## 还需要做什么：按优先级

### P0 — 首发数据与体验验收（当前主线）
- [x] 首发真实数据组合确定为豆瓣 Top 250 + 2025 四类年度榜单；热门/高分网页接口当前被 robots.txt 禁止，未绕过。
- [x] 首发真实数据扩充与导入验收：Top 250 250 条 + 年度榜单 38 条，共 288 个唯一影片、288 条榜单项、5 个快照；跨榜重复 0。
- [x] 导入质量闸门通过：SQLite integrity_check=ok，foreign_key_check=0；新影片 genre/region 关联缺失父级 ID 的问题已修复并加入回归测试。
- [x] 新增首发数据质量审计器，报告年份/评分/评价人数/演员/类型/地区/海报/简介等字段覆盖率，不推断或伪造缺失值。
- [x] 新增 opt-in GitHub Actions 数据扩充链路：采集 Top 250，合并已验证的 2025 年度四榜，dry-run、覆盖率审计、导入独立临时 SQLite、验证去重/完整性/外键，并保留 JSON artifact。
- [ ] 对合并后的 288 条真实数据完成 Playwright 浏览器验收（Top 250、年度四榜、详情、搜索）；专用 CI job 已加入，将复用本轮已验证的 5 份真实 JSON artifact，等待本轮复验。
- [ ] 为榜单条目补充可靠的影片详情数据（评价人数、导演、演员、简介等），保存来源/采集时间并允许缺失；遵守来源访问规则和速率限制。
- [ ] 完成前端真实数据视觉 QA，重点检查空值、长标题、海报失败、分页、移动端布局和异常提示。
- [ ] 完成真实数据收藏、历史快照、排名比较等完整用户流程验收。

### P1 — 部署前演练（仍在隔离环境，不触碰生产）
- [ ] 在临时目录/隔离主机完整演练 Compose 启动、显式初始化、数据导入、readiness、备份、恢复和升级/回滚。
- [ ] 检查配置默认值、密钥注入、反向代理信任边界、容器权限、数据卷和日志策略。
- [ ] 明确 NAS 资源预算、目录归属、备份落点及回滚路径；补充实际硬件性能测量方案。
- [ ] 将 NPM 与 Xiaoya 集成验收步骤写成可执行检查清单。

### P2 — 可选数据源与增强项
- [ ] 如果决定启用 Scout，再单独验证 Scout 只读快照适配和字段映射；不把 Scout 作为当前项目存在与否的前置条件。
- [ ] 根据真实数据规模和实测搜索延迟，决定是否需要 FTS5；当前 10 万条 LIKE 查询 CI 基线不足以证明必须增加依赖。
- [ ] 根据数据源许可、稳定性和实际维护成本，决定是否增加定时采集；当前没有后台定时刷新。
- [ ] 官方 2026 榜单发布后再审查是否增加对应分类。

### P3 — 经明确审批后才做的生产部署
- [ ] 生产目录创建和权限设置。
- [ ] 在 NAS 上显式初始化 MovieHub 正式数据库。
- [ ] 首次生产数据导入和完整性检查。
- [ ] NPM 反向代理/HTTPS 配置及真实域名联调。
- [ ] 启动服务、readiness 检查、备份恢复抽检和回滚验证。

**P3 尚未开始。** 生产数据库初始化、NAS 部署、真实 Scout 挂载/导入、NPM 配置变更和任何服务重启均须单独审批；本项目当前阶段不会自动执行这些操作。

## 进度判断

| 交付领域 | 当前判断 |
|---|---:|
| 产品范围与总体架构 | 完成 |
| 独立数据库基础、迁移和初始化 | 完成 |
| 后端核心 API 与导入安全 | 基本完成 |
| 榜单采集/规范化/批量导入 | 已实现；真实年度数据已在临时库演练 |
| 首发数据丰富度与内容验收 | 进行中 |
| 前端核心功能与自动化测试 | 基本完成；视觉 QA 待做 |
| 容器、备份恢复和运维文档 | 已实现；目标环境演练待做 |
| NAS/NPM 实际联调与部署 | 未开始 |

**整体约 78%。** 代码基础和自动化验证已经相当完整；剩余工作不是继续等待一个不存在的 MovieHub 源库，而是补齐首发内容、真实数据端到端验收、视觉 QA、隔离部署演练和最终生产部署。首发真实数据集和临时库导入已经形成可重复、可审计的 CI 交付；浏览器 QA、元数据补全、隔离部署演练和最终生产部署仍未完成。
