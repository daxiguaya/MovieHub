# MovieHub 项目总进度与交付清单

> **更新基线：2026-11-24（NAS 实际验收更新）**  
> 仓库：`daxiguaya/MovieHub`  
> 工作分支：`main`  
> 当前阶段：已部署，首发数据导入与最终验收（Live acceptance）  
> 整体进度估算：**约 90%**。这是交付范围估算，不是测试通过率。

## 2026-11-25 合并更新

- PR [#21](https://github.com/daxiguaya/MovieHub/pull/21) 已合并到 `main`（合并提交 `63db97ad9d939ce74a3af4805c9d573f83338bfb`）。
- PR [#20](https://github.com/daxiguaya/MovieHub/pull/20) 也已合并：MovieHub 容器更新后执行 NPM 配置校验并平滑 reload，以刷新上游 DNS；不会重启 NPM 容器。
- 随后补强了生产 rollout：备份 SQLite 后先停止 MovieHub 后端，在新镜像的一次性容器中执行 schema v4 迁移，再启动 MovieHub 前后端；若迁移/启动失败，回滚数据库和旧镜像。NPM 仍只做平滑 reload，不重启容器。
- 生产 rollout 和 `.env` 小雅配置检查的后续修订已通过最新主分支 CI（提交 `e02adb8d2261bc8b3a199355e304b83f915c0f02`）：Backend、Frontend、Compose smoke、Browser E2E 全部通过。
- 本轮 CI 已通过 Backend、Frontend/type-check、Compose smoke 和浏览器端到端测试。
- 代码新增 schema v4：豆瓣评价人数允许为 `NULL`，迁移会将旧数据中作为缺失占位的 0 转为 NULL；新增在线收藏与榜单影片的严格身份关联；Top 250/年度详情按需通过 TMDB 严格匹配补充临时简介；小雅地址改由 `.env` 提供；搜索筛选状态修复；新增豆瓣实时热门手动刷新脚本。
- **以上代码已合并，但尚未完成 NAS 二次 rollout。** NAS 基础实例已部署；生产库上次确认仍为 schema v3。必须通过 `deploy/rollout_online_discovery.sh --check` 预检，再经人工确认执行 `--deploy`，完成备份、schema v4 迁移、镜像更新和实时验收；不得跳过迁移直接替换后端。
- 豆瓣热门/高分采集仍是手动、受 robots.txt 约束的操作；若来源拒绝访问，脚本停止，不绕过限制。新增热门脚本不代表已经成功采集或导入数据。

## 一句话结论

MovieHub 已有独立 SQLite 数据库、核心 API、React 前端、榜单采集/导入链路、容器与备份恢复工具。首发真实数据为 5 个快照、288 条榜单项、288 个唯一影片；已在 GitHub Actions 临时数据库完成导入，并通过桌面、390px 移动端及真实收藏链路浏览器验收。

**NAS MovieHub 实例已部署并通过基础连通性、健康检查、NPM 路由和数据库备份恢复验收。** 但 NAS 正式数据库目前只有 7 个内置榜单定义，尚未导入 5 个真实快照 / 288 条榜单项；GitHub Actions 的真实数据验收仍属于隔离环境，不等于生产数据已经导入。

## 重要边界

- MovieHub 使用自己的 SQLite 数据库；NAS 基础实例已部署。Douban Scout 仅为可选外部只读导入源，不是 MovieHub 的源库或初始化前置条件。
- Douban Scout 是可选的外部只读数据源/导入适配器，不是当前项目初始化或数据库重构的前置条件。
- 当前首发数据来自允许访问的豆瓣 Top 250 页面和已验证的 2025 官方年度榜单。
- 豆瓣 robots.txt 禁止访问的热门/高分接口已停止使用，不绕过访问限制。
- NAS 部署与 NPM 路由已由用户实际完成；后续任何 NPM 修改、服务重启、生产数据导入仍需按单独步骤审查，不擅自重启现有服务。
- 真实来源未提供的字段保持缺失；不根据片名或其他信息推断、伪造评价人数、导演、演员或简介。

## 已完成

### A. 产品与架构
- [x] 首发用户路径：榜单发现 → 影片详情 → Xiaoya 搜索跳转。
- [x] 明确 MovieHub 不负责下载、播放和媒体库管理；由 Xiaoya、Jellyfin、SmartStrm 承担各自职责。
- [x] React + TypeScript + Vite 前端、FastAPI 后端、独立 SQLite；不引入 Redis、MySQL、Elasticsearch 等额外基础设施。

### B. 数据库与后端
- [x] MovieHub 独立 SQLite schema、ORM/schema 一致性校验、内部 MovieHub ID 关系。
- [x] 显式空库初始化、schema 版本检查、迁移前备份、完整性/外键校验和失败回滚。
- [x] 缺失数据库时 API 返回明确 503，不在应用启动或请求过程中偷偷创建数据库。
- [x] 榜单快照按榜单/日期隔离，支持历史快照、同日替换、排名比较和批量原子导入。
- [x] 影片搜索/筛选、详情、海报、收藏、导入状态等主要 API。
- [x] Scout 可选只读导入适配器：增量/全量、批次、记录级 SAVEPOINT、收据/检查点、重试与崩溃恢复。
- [x] 输入校验、身份冲突、媒体类型冲突、年份/评分/整数边界、导入路径与符号链接安全。
- [x] 海报抓取 SSRF 防护：HTTPS CDN 白名单、DNS 地址校验、逐跳重定向校验、响应大小/MIME/文件签名限制。
- [x] **schema v3 字段级元数据来源追踪**：记录字段名、来源、来源 URL、采集时间和字段值 SHA-256 指纹，不重复存储字段明文；已通过 Backend CI 和真实数据导入校验。

### C. 榜单采集与首发真实数据
- [x] 豆瓣 Top 250 保守采集器：先检查 robots.txt、至少 2 秒请求间隔、尊重 Crawl-delay、遇到 401/403/429 即停止，不尝试绕过；慢响应超时提高到 30 秒，不重试、不绕过。
- [x] 2025 官方四类年度榜单：电影与剧集分开，保留真实排名，不补造缺失名次。
- [x] 四份年度榜单通过导入预检；数据作为 GitHub Actions artifact 保存，不把抓取数据提交进 Git。
- [x] 2025 年度四榜真实导入演练：4 个榜单、38 部影片、38 条榜单项；SQLite integrity ok、外键错误 0。
- [x] 首发数据扩充至 **5 个快照 / 288 条榜单项 / 288 个唯一影片 / 跨榜重复 0**：Top 250 250 条 + 2025 年度四榜 38 条。
- [x] 真实数据导入触发的 genre/region 关联父级 ID 问题已修复，并增加回归测试。
- [x] 数据质量审计器报告字段覆盖率；已修复当前页面文本解析，评价人数 250/250、导演 238/250、演员 233/250；未提供字段不伪造。
- [x] opt-in GitHub Actions 数据链路：采集、dry-run、质量审计、导入临时 SQLite、去重/完整性/外键检查、artifact 留存。

### D. 前端与真实数据浏览器验收
- [x] 首页发现、榜单页、历史日期选择、分页。
- [x] 搜索筛选：关键词、电影/剧集、评分、年份、类型/地区等条件。
- [x] 详情页、海报展示、豆瓣链接、Xiaoya 跳转。
- [x] 收藏列表、添加/移除和备注交互。
- [x] 历史榜单排名变化展示。
- [x] 前端回归测试、Playwright Chromium fixture E2E。
- [x] 真实数据桌面浏览器旅程：Top 250 与 2025 四榜、详情、搜索。
- [x] **真实数据移动端浏览器验收**：390×844 视口下 Top 250 榜单、影片详情、搜索结果均无横向溢出。
- [x] **真实收藏链路浏览器验收**：从真实 Top 250 进入详情，加入收藏、在收藏页读取，再移除收藏；经可信代理注入服务端 API key，实际写入隔离 SQLite。
- [x] 最新完整验证 run [#45324728215](https://github.com/daxiguaya/MovieHub/actions/runs/45324728215)：Backend、Frontend、普通 fixture E2E、真实数据浏览器 E2E、首发数据采集/导入全部 success。性能基准、旧年度 rehearsal 和年度重新采集为 skipped，不计入通过。

### E. 部署、运维和安全
- [x] 后端/前端 Dockerfile、Compose 服务定义。
- [x] 非 root 容器、只读根文件系统、能力收缩、no-new-privileges、资源/PID 限制和独立持久化卷。
- [x] Compose 不直接发布 NAS/LAN 服务端口。
- [x] 显式一次性数据库初始化；容器启动不自动建库或迁移。
- [x] SQLite 在线备份、SHA-256 manifest、保留策略、校验恢复、恢复前回滚副本。
- [x] 健康检查/readiness、配置模板、部署/备份恢复/导入 runbook。
- [x] GitHub 隔离 runner 上真实启动双容器，验证未初始化 503、显式初始化、真实 API 读写、在线备份、停止 API 后恢复、重新启动 API、恢复值与回滚副本，再检查双容器健康状态。

## 当前首发数据质量缺口

最新真实采集审计（2026-11-24，Top 250 共 250 条）已验证：评价人数 250/250（100%）、导演 238/250（95.2%）、演员 233/250（93.2%）、年份 248/250（99.2%）、评分 250/250（100%）、原名 223/250（89.2%）、类型/地区各 248/250（99.2%）、海报 250/250（100%）。简介仍为 0/250。解析器已从当前页面可见文本提取评价人数和演职员，不再依赖旧版 class 选择器。

当前明确待补：
- [x] 对新采集的 Top 250 JSON artifact 复核评价人数实际覆盖率；已修复当前页面文本解析并在真实数据中验证 250/250。
- [x] 完成剧情简介来源专项研究并形成 [OVERVIEW-SOURCE-RESEARCH.md](OVERVIEW-SOURCE-RESEARCH.md)：TMDB 列为首选试验候选（非商业许可、署名、无 SLA、中文覆盖待实测）；Wikipedia 作为逐条核验的 CC BY-SA 备用；OMDb 因禁止索引/归档/分发排除；不使用受 robots 限制的豆瓣接口。
- [x] 新增只读 TMDB adapter 与覆盖率审计 CLI：优先已有 TMDB ID，其次 IMDb ID，最后严格标题+年份匹配；拒绝歧义/年份冲突；zh-CN/zh-TW 请求；报告只输出匹配元数据、简介长度和 SHA-256，不输出简介正文、不写数据库。Mocked API/backend tests passed。
- [x] 新增手动 GitHub Actions workflow [TMDB overview coverage audit](../.github/workflows/tmdb-overview-audit.yml)，从已验证首发 artifact 读取 2026-11-24 Top 250 快照（250 部影片），分别测量 zh-CN/zh-TW；运行需要仓库 Actions secret `TMDB_API_READ_TOKEN`。
- [x] 已配置 `TMDB_API_READ_TOKEN` 并完成真实只读 API 审计：Top 250 的 250 部影片分别检查 zh-CN/zh-TW，共 500 条语言记录；470 条确认有对应语言剧情简介（94%），其余 3 条歧义、4 条身份信息不足、21 条无严格匹配、2 条无简介均未接受。审计只输出匹配元数据/长度/SHA-256，不输出简介正文、不写数据库。
- [x] 导入时仅填补空字段，不覆盖已有来源数据；字段级来源、来源 URL、采集时间和内容指纹已落库并通过真实数据验证。
- [ ] 对多来源冲突制定优先级与审计规则；缺失值仍允许为空。
- [x] 收藏/取消收藏的真实 API 与 SQLite 写入、读取、删除流程已通过 Playwright。
- [ ] 继续验收空值、长标题、海报失败、分页、真实多日期历史快照和排名比较等流程。

## 尚未完成：按优先级

### P0 — 首发内容与体验收尾
- [x] 复核 Top 250 评价人数真实覆盖率并修复解析器与真实页面结构的差异。
- [x] 完成来源许可/稳定性/匹配方案研究及只读 TMDB adapter、CLI、mocked backend tests；详见 [OVERVIEW-SOURCE-RESEARCH.md](OVERVIEW-SOURCE-RESEARCH.md)。
- [x] 已配置只读 token 并完成 Top 250 的 500 条 zh-CN/zh-TW 真实 API 审计，简介可用覆盖率 470/500（94%）。
- [ ] 继续核验 TMDB 当前条款中缓存、持久化、再分发和展示限制；未核验/批准前不把简介写入 MovieHub 数据库。
- [x] schema v3 provenance migration、导入追踪逻辑和回归测试已通过 Backend CI 与真实数据持久化检查。
- [x] 真实数据收藏/取消收藏：通过 Playwright 经可信代理注入密钥，验证 live API 与临时 SQLite 的写入、列表读取、删除。
- [ ] 真实多日期历史快照选择、排名比较、分页和异常状态流程验收。
- [ ] 完成前端真实数据视觉 QA 和异常状态检查。

### P1 — 隔离环境部署演练（不触碰 NAS）
- [x] 在 GitHub 隔离 runner 完成 Compose 启动、显式初始化、readiness、API 读写、备份、恢复、恢复后 API 验证和回滚副本验收。
- [x] 完成隔离环境下真实规范化数据导入、schema v2→v3 镜像升级、容器 API 验证、备份恢复和回滚副本演练（CI #45350740671）。
- [ ] 检查密钥注入、反向代理信任边界、容器权限、数据卷和日志策略。
- [ ] 制定目标 NAS 资源预算、目录权限、备份落点和性能测量方案。
- [ ] 将 NPM 与 Xiaoya 集成验收步骤整理为可执行清单。

### P2 — 可选增强
- [ ] 如决定启用 Scout，再单独验证只读快照适配和字段映射。
- [ ] 根据真实数据规模和搜索延迟决定是否需要 FTS5。
- [ ] 根据来源许可、稳定性和维护成本决定是否增加定时采集；目前没有后台定时刷新。
- [ ] 官方 2026 榜单发布并核实后，再决定是否增加对应分类。

### P3 — NAS 部署与生产验收
- [x] NAS 项目目录、数据目录和备份目录已建立；容器 UID/GID 10001 写入权限已实测。
- [x] NAS MovieHub 独立数据库已显式初始化；上次确认 schema v3 readiness 正常，schema v4 rollout 待执行。
- [x] 前后端容器已部署并均为 healthy；无宿主机端口发布。
- [x] NPM `/moviehub/`、favorites 专用 location、导入路由拒绝规则和 HTTPS 外部访问已实测；DSM 根路径保持正常。
- [x] 首份数据库备份 SHA-256、文件大小、SQLite integrity、外键和 13 张表均已校验。
- [x] 临时 SQLite 恢复演练通过，13 张表记录数与备份逐表一致，未修改生产数据库。
- [ ] 确认 API Key 已完成轮换，且 `.env` 与 NPM favorites location 使用同一把新密钥。
- [ ] 完成 schema v4 安全 rollout 后，再将经审核的首发数据导入 NAS MovieHub 数据库，并完成 API/前端验收。
- [ ] 完成 Xiaoya 搜索跳转及异常状态最终验收。

**NAS 基础部署与备份恢复验收已完成；生产电影/榜单数据导入尚未完成。** Scout 仍是可选只读来源，不得把 Scout 数据库当作 MovieHub 目标库。

## 进度判断

| 交付领域 | 状态 |
|---|---|
| 产品范围与总体架构 | 完成 |
| 独立数据库基础、初始化和迁移 | schema v3 与字段来源追踪已通过 CI |
| 后端核心 API 与导入安全 | 基本完成 |
| 榜单采集、规范化和真实导入 | 已完成首发数据演练 |
| 首发详情元数据丰富度 | 进行中 |
| 前端核心功能与桌面/移动端真实数据 E2E | 榜单、详情、搜索、收藏链路自动化验收通过；视觉 QA 待做 |
| 容器、备份恢复和运维文档 | 已实现；真实 288 条榜单项导入、schema v2→v3、双容器 API、备份恢复/回滚均在隔离 CI 通过 |
| NAS/NPM 实际联调与基础部署 | 已完成；生产首发数据导入待完成 |

**整体进度估算维持约 90%。** 本轮新增两项真实验收：TMDB Top 250 的 500 条简繁体语言记录只读审计，470 条可用（94%）；以及 5 个真实快照/288 条榜单项在 schema v2→v3 升级后的双容器导入、API、备份恢复和回滚闭环。TMDB 审计不写数据库，因此 MovieHub 当前 synopsis 字段仍为 0/250；在缓存、持久化、再分发和展示条款核验完成前，不启动简介导入。下一步优先完成 TMDB 条款审查，再决定是否增加 NULL-only overview importer 与 attribution UI；同时补齐真实多日期历史、Scout 只读导入演练和前端边界 QA。最新真实数据导入/升级 CI [#45350740671](https://github.com/daxiguaya/MovieHub/actions/runs/45350740671) 与主 CI [#45350740713](https://github.com/daxiguaya/MovieHub/actions/runs/45350740713) 均通过。

## 2026-11-24 — Pagination, history, search-filter acceptance expansion

- [x] Add Playwright coverage for chart first/last-page traversal, ensuring page-one items remain visible after loading the final page.
- [x] Add Playwright coverage for switching to a historical snapshot after pagination and ensuring items from the previous snapshot are cleared.
- [x] Add Playwright coverage for comparing two dates and rendering moved/new ranking states.
- [x] Add Playwright coverage for submitting combined search filters (keyword, media type, rating, rating count, year range, included/excluded genres, region, and sort).
- [x] Add Playwright coverage for zero-result and API-error states.
- [x] Extend the backend chart API integration test to traverse cursor pages and request a historical snapshot through the HTTP API.
- [x] Add backend API integration coverage proving combined movie filters apply together, including AND genre matching and excluded genres.
- [x] Fix Playwright strict-mode selectors by scoping rank-comparison assertions to the relevant result row.

**Verification:** CI [#45334459741](https://github.com/daxiguaya/MovieHub/actions/runs/45334459741) passed: backend 265 passed / 4 skipped; frontend unit tests, type-check/build, and container builds passed; browser E2E 10 passed / 4 skipped. The four skipped browser cases are the separately opt-in real first-launch dataset journeys, so this run verifies fixture-based browser flows and isolated API/SQLite integration, not a new real-source collection or real multi-date dataset. Performance benchmarks and opt-in collection/import jobs were also skipped and are not counted as passed.

**Progress remains approximately 83%.** This acceptance expansion closes important automated test gaps but does not change the outstanding real TMDB synopsis audit, real multi-date source-data verification, isolated Compose deployment rehearsal, or separately approved NAS deployment. No production database was initialized and no NAS service was changed.

## 2026-11-24 — Fresh real-source dataset and browser acceptance

- [x] Re-collect the robots-permitted Top 250 snapshot and audit its source metadata.
- [x] Import the fresh Top 250 snapshot plus all four retained official 2025 annual charts into a disposable SQLite database.
- [x] Verify 288 chart items, 288 unique MovieHub movies, five snapshots, SQLite integrity `ok`, and zero foreign-key errors.
- [x] Run the real-data browser journeys against the freshly imported database: Top 250, all 2025 annual snapshots, narrow mobile viewport, and live favorite add/list/remove.

**Run:** [#45334724102](https://github.com/daxiguaya/MovieHub/actions/runs/45334724102). The first-launch collection/import job and the real-data browser job both succeeded; the real-data browser suite passed **4/4**. The normal backend/frontend jobs also succeeded. The regular fixture E2E job has since completed successfully in the same run; its browser tests, backend, frontend, and container build jobs all succeeded. Performance benchmarks and the separately opt-in annual collection/import rehearsal jobs were skipped and are not counted as passed.

Fresh Top 250 source audit: rating 250/250, rating count 250/250, directors 238/250, actors 233/250, year 248/250, original title 223/250, genres 248/250, regions 248/250, posters 250/250. **Plot overview remains 0/250**; no short reviews or taglines are substituted. This real-data run does not establish multiple distinct capture dates for the same chart; it verifies the available 2026-11-24 Top 250 and retained 2025 annual snapshots.

All work remained in disposable GitHub Actions storage. No NAS path, production database, NPM configuration, or NAS service was touched.


## 2026-11-24 — Chart pagination cursor hardening

- [x] Reject explicitly empty, malformed, zero, negative, and non-canonical chart pagination cursors instead of silently treating them as page one.
- [x] Decode URL-safe Base64 strictly and require a positive canonical decimal rank.
- [x] Return HTTP 400 with a stable error message for invalid cursors.
- [x] Extend the chart HTTP integration test to cover five invalid cursor forms and a valid cursor beyond the final rank (empty page, stable total, no next cursor).
- [x] Branch-head CI [#45339047025](https://github.com/daxiguaya/MovieHub/actions/runs/45339047025) and merge-gate CI [#45341969331](https://github.com/daxiguaya/MovieHub/actions/runs/45341969331) passed the cursor regression suite.

This is API input hardening only. It does not claim real multi-date source snapshots, synopsis coverage, or deployment completion. Overall delivery estimate remains **83%**. All tests continue to use disposable SQLite; no NAS, production database, NPM configuration, or service was touched.


## 2026-11-24 — Optional Scout mount and cursor regression follow-up

- [x] Remove the hard requirement for `MOVIEHUB_IMPORT_PATH`; Compose now mounts a tracked empty directory read-only when Scout is not configured.
- [x] Keep explicit Scout configuration supported as a read-only `/imports` mount.
- [x] Update `deploy/.env.example` and deployment instructions so Scout is clearly optional.
- [x] Expand CI Compose validation to check both no-Scout and explicit-Scout configurations.
- [x] Strict cursor validation surfaced one older unit test that still expected malformed cursors to be silently ignored; update that test to assert the new HTTP/service contract.
- [x] Branch CI [#45336510682](https://github.com/daxiguaya/MovieHub/actions/runs/45336510682) completed successfully after the cursor regression-test correction.

The first cursor-hardening CI attempt found an outdated test expectation (264 passed, 1 failed, 4 skipped); it was corrected. The successful follow-up CI completed with **265 backend tests passed, 4 skipped, 1 warning; 10 browser E2E passed, 4 opt-in real-data journeys skipped; frontend tests/build and both container builds passed**. Both Compose validation modes passed: Scout omitted and Scout explicitly configured read-only. Performance and real-data collection/import jobs were skipped in this fixture run and are not counted as passed. Overall estimate remains **83%**; no deployment or production data operation was performed.


## 2026-11-24 — Isolated deployment lifecycle rehearsal

- [x] Add one continuous temporary-directory lifecycle test: uninitialized readiness → schema initialization → ready state → data write → verified backup → later write → restore → restored readiness and data verification.
- [x] Verify the pre-restore rollback copy retains the later state.
- [x] Verify schema version 3, SQLite integrity, and foreign-key consistency after restore.
- [x] Add a safety regression test proving initialization refuses an existing external SQLite database and leaves its table/data untouched.
- [x] Branch-head CI [#45339047025](https://github.com/daxiguaya/MovieHub/actions/runs/45339047025) passed the lifecycle tests: backend 267 passed / 4 skipped; frontend regression tests, type-check/build, browser E2E, both container builds, and both Compose configuration modes succeeded.

The database lifecycle tests passed in temporary SQLite. The live two-container Compose rehearsal also passed in isolated GitHub Actions [#45341969331](https://github.com/daxiguaya/MovieHub/actions/runs/45341969331): both images built and containers started; API liveness worked before initialization; readiness correctly returned 503 until explicit initialization; the seeded chart API and frontend HTTP both responded; backend and frontend health checks became healthy; and the isolated Compose project was removed. This exposed and fixed an Nginx write to /var/cache/nginx under the read-only root filesystem by routing all Nginx temporary paths to /tmp tmpfs. This is an isolated CI runtime rehearsal, not a NAS deployment or NPM integration. Overall progress remains **83%** because source-data licensing/overview coverage, real multi-date history, and production deployment work remain.


## 2026-11-24 — Mainline integration

- [x] Opened PR [#1](https://github.com/daxiguaya/MovieHub/pull/1) from `phase4/database-foundation` into `main`.
- [x] Merge-gate CI [#45341969331](https://github.com/daxiguaya/MovieHub/actions/runs/45341969331) passed: backend, frontend, browser E2E, isolated Docker Compose smoke, and both container builds.
- [x] Squash-merged PR #1; `main` now points to `0649a4d209f99d91bb192b8c544eed2cd63a993e`.

The merge promotes the current implementation to the repository's default branch. It does not deploy the application or initialize a production database.


## 2026-11-24 — Live container backup/restore rehearsal

- [x] Run the documented backup command inside the actual backend container while the API is running.
- [x] Verify a seeded sentinel movie through the live API before backup.
- [x] Mutate the sentinel after backup and verify the changed value through the API.
- [x] Stop the backend container and restore the selected backup through a one-shot Compose container.
- [x] Restart the API and verify the original value is served again; verify the pre-restore rollback copy contains the changed value.
- [x] Verify backend/frontend container health checks and cleanup of the isolated Compose project.
- [x] Compose lifecycle job passed in CI [#45343969389](https://github.com/daxiguaya/MovieHub/actions/runs/45343969389); backend and frontend build/test jobs passed. Browser E2E was still running at the time of this status update.
- [x] Optimize CI browser installation to use Playwright's headless Chromium shell for the headless E2E suite; validation [#45344225088](https://github.com/daxiguaya/MovieHub/actions/runs/45344225088) passed with 10 browser E2E tests and 4 skipped.

This remains isolated CI verification. No NAS, NPM, Scout source database, or production data was accessed. Overall progress remains **83%** pending real overview coverage/licensing, genuine multi-date source history, and eventual production deployment.


The documentation/main-head CI [#45344314269](https://github.com/daxiguaya/MovieHub/actions/runs/45344314269) also passed all required jobs: backend 267 passed / 4 skipped, browser E2E 10 passed / 4 skipped, frontend tests/type-check/build, both image builds, and full isolated Compose backup/restore rehearsal. Optional external-source collection and performance jobs remained skipped by design.


## 2026-11-24 — Compose lifecycle rehearsal completed

- [x] Complete the live two-container Compose backup/restore rehearsal in CI [#45343969389](https://github.com/daxiguaya/MovieHub/actions/runs/45343969389): baseline API value → backup → changed API value → stop API → one-shot restore → restart API → restored value → rollback-copy verification.
- [x] Verify both container health checks and isolated project cleanup.
- [x] Switch headless browser CI to Playwright Chromium headless shell; [#45344225088](https://github.com/daxiguaya/MovieHub/actions/runs/45344225088) and documentation/main-head CI [#45344314269](https://github.com/daxiguaya/MovieHub/actions/runs/45344314269) passed, with 10 browser E2E passed / 4 skipped and backend 267 passed / 4 skipped.

The remaining 16% is concentrated in licensed/accurate synopsis coverage, genuine same-chart multi-date source history, final import/upgrade rehearsal, and separately approved production integration/deployment. No NAS or production database was touched.


## 2026-11-24 — Real TMDB audit and real-data container upgrade rehearsal

- [x] Run the real read-only TMDB audit against the verified 2026-11-24 Top 250 snapshot: 250 unique movies × 2 locales = 500 language records.
- [x] Confirm 470/500 locale records have a non-empty matching synopsis (**94.0% overall**): zh-CN 238/250 (95.2%), zh-TW 232/250 (92.8%).
- [x] Keep uncertain results out of the accepted set: 3 ambiguous, 4 insufficient identity, 21 no exact match, and 2 matched records with no overview. No synopsis text is written to the report or database.
- [x] Add a separate workflow, [real-data-compose-upgrade.yml](../.github/workflows/real-data-compose-upgrade.yml), so the long real-data rehearsal cannot destabilize required Backend CI.
- [x] Create a populated disposable schema-v2 SQLite database with a sentinel, then use the actual `scripts.migrate` runner to upgrade to schema v3. The migration passed ORM/schema, integrity and foreign-key validation and retained its verified v2 pre-migration backup.
- [x] Import all five normalized real snapshots into the upgraded database: **289 movies including the sentinel, 5 chart snapshots, 288 chart items**.
- [x] Verify field provenance was written for imported metadata: actors 233, directors 276, original_title 223, rating 288, rating_count 250, year 248 observations.
- [x] Verify the live API: readiness passed, five charts returned, Top 250 API reported 250 total entries and served a 50-item page.
- [x] Create a verified post-import backup; mutate the sentinel; stop the API; restore via the documented one-shot container; restart and verify the original sentinel plus all 5 snapshots/288 chart items returned.
- [x] Verify the pre-restore rollback copy retained the post-backup mutation and both backend/frontend container health checks reported healthy.
- [x] Real-data rehearsal [#45350740671](https://github.com/daxiguaya/MovieHub/actions/runs/45350740671) passed every step. Main CI [#45350740713](https://github.com/daxiguaya/MovieHub/actions/runs/45350740713) passed backend **267 passed / 4 skipped**, frontend regression/type-check/build, browser E2E **10 passed / 4 skipped**, and the standard isolated Compose smoke test. Optional benchmark/collection jobs were skipped and are not counted as passed.

The TMDB audit is a coverage/matching dry-run only. It does not authorize bulk synopsis persistence or redistribution. The real-data rehearsal used only disposable GitHub Actions storage and was fully cleaned up. **No NAS, NPM, production database, Scout source database, or NAS service was accessed or changed.** Production deployment remains a separate, not-yet-started approval stage.

## 2026-11-24 — Expanded synopsis audit scope and legal hold

- [x] Rechecked the current official TMDB FAQ and rate-limit documentation: non-commercial developer use only, attribution/approved logo and exact disclaimer required, no SLA, and respect changing request limits/HTTP 429.
- [x] Followed TMDB's official Getting Started link to its Terms of Use. The primary terms page blocks automated retrieval; a third-party transcription dated 2026-11-10 quotes a six-month maximum cache, non-commercial restriction, non-transferable/non-sublicensable license, derivative and AI-related restrictions. This is documented as a risk signal, not treated as the controlling official text.
- [x] Set a hard compliance hold: no synopsis schema v4, no persistent importer and no synopsis database writes until the owner has reviewed the current official terms and approved the retention/display model.
- [x] Extended the read-only audit workflow to separately measure Top 250 (snapshot 2026-11-24) and the four annual charts (snapshot 2026-11-23, 38 unique movie/TV records), both in zh-CN and zh-TW. Audit run [#45352538897](https://github.com/daxiguaya/MovieHub/actions/runs/45352538897) completed successfully and uploaded both reports without synopsis text.
- [x] Review the annual-chart report: 38 unique items × 2 locales = 76 records; all 76 were classified `insufficient_identity` because the official annual snapshot contains no release year and the strict matcher requires title+year. This is **not** a measured 0% TMDB overview coverage; no candidate lookup was attempted for these rows.
- [ ] Re-run the annual audit after the yearless title+director identity enhancement in PR [#2](https://github.com/daxiguaya/MovieHub/pull/2). The enhancement requires exact title and matching TMDB credits, preserves multi-word director names, and continues to reject ambiguous/unverified matches.
- [ ] Complete a second genuine Top 250 capture on a different date before claiming real Top 250 historical movement. Do not clone today's data and label it historical.
- [ ] Complete Scout read-only integration rehearsal and remaining frontend edge-state QA in isolated CI.

The official terms page was not machine-readable in this research session, so the project deliberately does not infer permission for indefinite synopsis retention. No production resources were touched.


## 2026-11-24 — Annual-chart identity gap found and fixed in review

- [x] Completed the expanded TMDB audit. Top 250 remained 470/500 (94.0%) with the previously measured per-locale breakdown. The four annual charts returned 76/76 `insufficient_identity` because those source rows legitimately do not carry a release year; the audit did not attempt weak title-only matches.
- [x] Identified the cause in the matching path and annual parser: yearless annual rows could not use the existing strict title+year resolver, and director names containing spaces were being split into fragments.
- [x] Opened [PR #2](https://github.com/daxiguaya/MovieHub/pull/2): a yearless record can now be accepted only after exact normalized title plus a matching director from TMDB credits. Ambiguous candidates remain rejected; no-director rows remain insufficient identity. Annual parsing now splits only explicit director separators and preserves multi-word names.
- [ ] Wait for PR checks, merge only after CI passes, then rerun the annual read-only audit and report measured coverage separately by locale.

The PR changes only read-only matching and parsing. No synopsis text is persisted; no production database or NAS was accessed.


## 2026-11-24 — Localized annual director matching: real audit and merge

- [x] PR [#5](https://github.com/daxiguaya/MovieHub/pull/5) merged to `main` as squash commit `a70d2a38f6edf35856acd8b018a9c1faf238eaf9`.
- [x] The PR's backend, frontend, Compose smoke, and frontend E2E checks passed. Optional first-launch collection, annual collection, performance and browser real-data jobs were skipped in that PR check suite and are not counted as passed.
- [x] Read-only TMDB audit [#45366496227](https://github.com/daxiguaya/MovieHub/actions/runs/45366496227) completed successfully against the retained first-launch artifact: Top 250 (250 titles × zh-CN/zh-TW) and 2025 annual charts (38 titles × zh-CN/zh-TW).
- [x] Top 250 result: zh-CN 238/250 (95.2%), zh-TW 232/250 (92.8%); combined 470/500 (94.0%). Remaining statuses include ambiguous identity, no exact match, and missing localized overview; none were force-matched.
- [x] Annual chart result after localized TMDB person-name resolution: zh-CN 31/38 (81.6%), zh-TW 31/38 (81.6%); combined 62/76 (81.6%). This improves on the previous 76/76 `insufficient_identity` result. The remaining 14 records remain `no_exact_match`; exact title/alternative-title and director identity checks remain enforced.
- [x] Audit artifact contains coverage reports only, no synopsis text. The run did not write to any database and did not access the NAS.
- [ ] Continue the legal hold: do not persist or redistribute TMDB overview text until the current official terms, retention/cache limits, attribution, logo and display requirements are reviewed and explicitly approved.
- [ ] Finish deployment gate: verify NAS-specific Docker network existence/IP trust boundary, UID/GID and directory ownership, secrets, protected import endpoints, logs, resource budget and backup destination before any deployment.
- [ ] Perform first deployment only after explicit go-ahead; initialize a new MovieHub database (never Scout's database), import verified data, then test readiness, NPM routing, backups and rollback.

**Current delivery estimate remains approximately 87%.** The matching fix and real-data audit are complete and merged; the estimate does not include NAS deployment. MovieHub still has no production database or NAS instance.


## 2026-11-24 — Deployment preflight added and CI verified

- [x] Added `deploy/preflight.py`, a read-only Synology/Linux preflight. It checks required Compose support/configuration, the API-key placeholder/length, `.env` file exposure, frontend runtime JSON, expected data/backup directories and likely UID/GID mode-bit access, external NPM network membership, likely NPM container identity, and fixed container-name conflicts.
- [x] Preflight inspects rendered Compose JSON and blocks unexpected published host ports or writable container root filesystems. It does not create directories, change permissions, start/stop containers, initialize SQLite, change Docker networks, or edit NPM.
- [x] Documented the preflight in [DEPLOYMENT.md](DEPLOYMENT.md); DSM ACLs and saved NPM proxy/TLS/access-control rules still require host-side verification.
- [x] Added Python syntax compilation of the preflight to Backend CI. Final verification [#45369731877](https://github.com/daxiguaya/MovieHub/actions/runs/45369731877) passed: backend tests/build, frontend tests/build, frontend browser E2E, and full disposable Compose backup/restore smoke.
- [x] Removed the obsolete `phase4/**` push trigger; `main` is the active development line.
- [ ] NAS-specific host checks remain pending because no NAS execution channel is connected. Do not treat CI as NAS validation.
- [ ] Before first deployment, verify actual NPM IP/trusted proxy range, DSM ACL write access, `.env` mode, import route denial, TLS/access policy, and backup destination on the NAS.
- [ ] TMDB synopsis persistence remains on legal hold pending review of official terms, cache/retention, attribution, logo and display requirements.

**Current delivery estimate: approximately 88%.** This is a development estimate, not a deployment percentage. The preflight script is implemented and CI-verified, but no NAS deployment or production database exists.


TMDB attribution and persistent-overview retention findings are tracked separately in [TMDB-API-COMPLIANCE.md](TMDB-API-COMPLIANCE.md). The current official FAQ confirms non-commercial-use and attribution/logo/notice requirements, but does not settle persistent synopsis caching duration; overview persistence remains disabled pending review of the full accepted Terms of Use and clarification where needed.


## 2026-11-24 — Import endpoint boundary and NPM deny policy tightened

- [x] Added an explicit API-key regression test for `POST /api/charts/import`; missing and incorrect keys must both return HTTP 401 before any chart import can execute.
- [x] Verified existing favorites endpoints require the API key and existing Scout import endpoints require the API key plus confinement to the read-only import mount (including symlink escape rejection).
- [x] Expanded the NPM deployment runbook with server-level deny locations for `/api/import` (including `/api/import/status`) and `/api/charts/import`. These rules take precedence over the general `/api/` proxy location; the key is injected only for favorites.
- [x] Full standard CI for the preceding code commit passed backend tests, frontend tests/build, E2E, and Compose backup/restore smoke in [run #45370748614](https://github.com/daxiguaya/MovieHub/actions/runs/45370748614).
- [x] The new chart-import API-key test passed in the backend job of [run #45382554819](https://github.com/daxiguaya/MovieHub/actions/runs/45382554819); frontend, Compose and browser E2E jobs were still running at the time this note was prepared.
- [ ] Confirm the newest documentation-head workflow after the NPM deny runbook update.
- [ ] Apply and validate the NPM deny rules on the NAS only during the separately approved deployment window; no NPM configuration has been changed by this work.
- [ ] NAS host checks, independent database initialization, first data import, live backup/restore and TMDB synopsis licensing decision remain outstanding.

**Development delivery estimate remains approximately 88%; NAS deployment remains 0%.** The added API test and NPM runbook improve the deployment security gate but do not count as a NAS-side validation.


## 2026-11-24 — NAS live deployment and backup/restore acceptance

This section supersedes older historical notes above that say NAS deployment has not started.

- [x] Deployed baseline: `main` commit `1c6ceffbef43cc10b8261f7e85082ebe87a4f35c`.
- [x] NAS frontend and backend containers are both healthy; backend logs show normal startup and repeated `/api/ready` HTTP 200.
- [x] Public HTTPS path checks passed for `/moviehub/`, `/moviehub/search`, and `/moviehub/api/ready`; protected import paths return 404; DSM root remains HTTP 200.
- [x] Fixed the no-trailing-slash redirect to use a relative redirect and preserve external port `:18443`.
- [x] Production database readiness reports schema version 3. It currently has 13 tables, 7 built-in chart definitions and no imported movie/chart snapshot rows.
- [x] Backup `moviehub-20261124T120602000694Z`: 200704 bytes; manifest SHA-256 equals the actual file hash; SQLite integrity `ok`; foreign-key errors 0.
- [x] Isolated temporary restore drill passed: schema migration version 3, 13 tables, 0 foreign-key errors, and identical row counts in every table. Temporary restore directory was removed. The production database and running containers were not changed by this drill.
- [ ] API-key rotation remains unconfirmed. The backend restart/readiness result does not prove that `MOVIEHUB_API_KEY` was rotated or that the NPM favorites-only header was updated.
- [ ] Import the approved 5-snapshot / 288-row first-launch dataset into the NAS-owned database, after reviewing the exact artifact and CLI preflight. This is separate from the already-passed disposable CI import.
- [ ] TMDB overview persistence remains on legal hold; do not store synopsis text until the terms/retention decision is explicitly resolved.

**Current estimate: approximately 90%.** The remaining critical work is the API-key rotation check, controlled first-launch data import, and final live user-flow validation. No NPM restart or unrelated service restart is part of this next phase.
