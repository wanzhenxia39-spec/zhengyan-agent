# 股票投资顾问 Agent

输入一个 股票研究问题，双轴路由选择流程：快查、标准研究（单 Agent + 业绩复核 SOP）或争议深研（多专家 + 反证官 + 主席）。
输出**可追溯、可复核**的研究底稿，写入带版本链的决策档案。

> 仅研究与模拟，不构成投资建议，不承诺收益，不执行任何交易。

## 快速开

### 方式一：Docker 一键启动（推荐，Windows / macOS / Linux 通用）

前置：安装并启动 Docker Desktop（Windows 需开启 WSL2）或 Linux 的 Docker Engine + Compose v2。

```bash
cp .env.example .env
```

Windows PowerShell 用 `Copy-Item .env.example .env`。填 `DEEPSEEK_API_KEY` 才能发起新研究；不填也能启动并浏览演示数据。

```bash
docker compose up -d --build
```

打开 http://localhost:8000 。首次启动会自动导入演示数据（12 只股票的 22 份档案、证据、RSI 账本与评测记录）。

```bash
docker compose exec app advisor research "复核贵州茅台 600519 最新一期半年报业绩，利润质量如何"
```

```bash
docker compose --profile test run --rm test
```

最后一条跑全部测试（虚构数据 + 假模型，不联网、不需要 Key）。想把数据库重置为演示数据：`docker compose down -v` 后再 `up`。国内网络构建慢时，在 `.env` 里打开 `PIP_INDEX_URL` / `NPM_REGISTRY` 两行镜像源。

本地决策小模型 Kev 依赖 Apple Silicon + MLX，Docker 里不包含；不配置时意图识别和路由判别自动退回大模型，功能不受影响。

### 方式二：宿主机直接运行（开发用）

前置：Python 3.12+；Node 18+；`uv`（`python3 -m pip install --user uv`）。没有 uv 时可用 `pip install -r requirements.txt -r requirements-dev.txt && pip install -e .` 代替 `uv sync`。

```bash
docker compose up -d mongo
```

```bash
uv sync
```

```bash
cp .env.example .env   # 填入 DEEPSEEK_API_KEY
```

```bash
npm --prefix web install && npm --prefix web run build
```

```bash
.venv/bin/advisor serve
```

Windows 下虚拟环境的命令在 `.venv\Scripts\` 里（如 `.venv\Scripts\advisor serve`）。

打开 http://127.0.0.1:8000 ：首页是产品介绍，「研究台」进入三栏工作台（左侧导航与档案标的、中间内容、右侧「问顾问」），证据点开即右侧「溯源」抽屉。前端开发模式：`npm --prefix web run dev`（5173 端口，自动代理 `/api`）。

命令行：

```bash
.venv/bin/advisor research "复核贵州茅台 600519 最新一期半年报业绩，利润质量如何"
```

加 `--route deep` 走多专家深研。评测：

```bash
.venv/bin/advisor eval routing
```

```bash
.venv/bin/advisor eval compare
```

```bash
.venv/bin/advisor eval update     # 持续更新：已重新研究的订阅提醒里，受影响结论是否被修正、没受影响的是否保留
```

底稿写入 `reports/`。测试：

```bash
.venv/bin/python -m pytest -q
```

## RSI：受控自进化

只改模型外面那一层：S1 经验卡、S2 路由参数、S3 检索模板（专家搜索侧重、相关度阈值、抓取站点名单）。改抓取站点名单属高风险：一次只加一个、只加不删，批准时必须写明理由。资产只追加（parent + change_reason + sha256），在用版本由账本事件推出。

```bash
.venv/bin/advisor rsi collect            # ① 从质询裁决/核验/路由评测/搜索记录收集坏案例（四要素）
```

```bash
.venv/bin/advisor rsi propose S1         # ② 优化器针对一个坏案例生成一个候选
```

```bash
.venv/bin/advisor rsi evaluate <run_id>  # ③④ 同台对比（基线/候选/关经验库 × 3 次）+ 六道门控
```

```bash
.venv/bin/advisor rsi approve <run_id>   # ⑤ 人工批准（单人阶段标出「自批」），再 release；变差则 rollback lessons --reason ...
```

Web「自进化」页：闭环节点亮灯、三个场景的坏案例、候选与门控指示灯、开/关经验库对照、版本血缘与一键回滚、继承证明（每份档案记录所用版本）。
研究时按标签召回 ≤3 张经验卡作为「方法提示」（不是证据、不是指令）；档案与底稿记录 `经验库 vN · 路由参数 vN · 检索模板 vN`。

## ##用户确认档案、个人情境官、订阅与增量复核

- **我的约束**（Web「我的约束」页）：可承受回撤、资金期限、关注/持有股票的购买理由。只有用户勾选确认才写入，每次保存是新版本；研究流程没有写入入口。保存后标出个人情境结论因此改变的档案（版本记录和档案页都会显示）。
- **个人情境官**（档案页「个人情境」卡）：把档案结论对照你确认过的约束——购买理由是否仍有已核验主张支持、近 250 日回撤是否超出承受度、资金期限与波动是否相容、结论是否完整、是否有待复核变化。纯本地规则，不调用模型，个人信息不出域；没确认的一律标「未知」。
- **订阅与增量复核**（Web「订阅与复核」页）：扫描新报告期财报、档案时点后的公告、超过阈值的价格变化，以及档案自己写的复核条件；按「主张 → 证据 → 报告期/行情时点」找出受影响的旧结论。没有变化不产生提醒，同一批变化只提醒一次；档案本身不改。「用新数据重新研究」带着受影响结论做一次标准研究，生成新版本并逐条对照旧结论。服务运行时每 `watch.scan_interval_hours` 小时自动扫描。

```bash
.venv/bin/advisor watch add 600519      # 订阅（需要已有档案）
```

```bash
.venv/bin/advisor watch scan            # 扫描全部订阅，可放进 cron
```

## ##策略卡与前向模拟盘（只模拟，不交易）

策略卡把「什么情况下纳入 / 移出观察组合」写成显式规则（字段来自档案 A 级指标与档案状态，如 PE 分位、波动、已核验主张数、待复核提醒数）。

- **前向模拟盘**：从开始日起逐日向前推进，不回填历史；只用当天以前可得的档案版本与行情；等权、整手、虚拟资金；每笔成交记录依据的档案版本与证据；当天移出的不当天回补。
- **晋级门控**（纯代码）：前向时长 ≥ `min_paper_days`、无未来数据、回撤不超上限、每笔可追溯、与在用版本同期收益不退化。
- **状态机**：草稿 → 模拟中 → 待晋级 → 已晋级 → 退役 / 回滚；改规则 = 追加新版本；晋级只能由人批准（单人阶段标「自批」）；一键回滚到上一个晋级过的版本。

```bash
.venv/bin/advisor strategy step         # 把模拟中的策略推进到今天
```

```bash
.venv/bin/advisor strategy submit SC-001 1
```

## 一次研究做了什么

争议深研：`route → collect → team_plan ⇉ 专家×N（并行、首轮隔离）→ blackboard → cross_exam → rebuttal → chair → deep_gate → commit`。

标准研究 / 快查：

```
intake → authorize → route → plan → collect → search → draft → verify → quality_gate → commit
                                       ↑                                      │
                                       └────────── 补证（最多 1 轮）────────────┘
```

| 节点           | 做什么                                                | 谁来做        |
| ------------ | -------------------------------------------------- | ---------- |
| intake       | 识别代码、意图、是否含个人敏感信息                                  | 快模型 + 规则   |
| authorize    | 含个人信息 → **暂停等用户确认**；交易意图 → 加边界说明                   | 规则 + 人     |
| route        | 快查 / 标准研究，绑定模型角色与预算                                | 规则         |
| plan         | 生成搜索词（必含一条风险/反证查询）                                 | 快模型        |
| collect      | 财报（只取 as_of 前已披露）、行情、公告；Decimal 计算同口径指标            | Skill      |
| search       | DeepSeek 搜索 → 过滤 → 聚类去转载 → 抓取白名单 → 清洗注入 → A/B/C 分级 | Skill + 规则 |
| draft        | 按证据起草事实/推断/假设/情景                                   | 强模型        |
| verify       | 证据存在、时点合法、等级足够、**数字可在引用证据中复算**                     | 规则         |
| quality_gate | 通过 / 补证 / 部分结论                                     | 规则         |
| commit       | 写入新版本档案（不覆盖旧版本）                                    | 规则         |

## 证据等级

| 等级  | 来源                      | 能支撑     |
| --- | ----------------------- | ------- |
| A   | 结构化财报、行情、巨潮公告、系统计算      | 结论与数字   |
| B   | 权威网页（authority≥3）且已抓取快照 | "发生了什么" |
| C   | 其他搜索结果                  | 只能触发补证  |

## 目录

```
config/            models.yaml（模型角色）、policies.yaml（权限/预算/出域）、sites.yaml（抓取白名单/黑名单）
src/advisor/
  contracts/       Pydantic 契约：EvidenceCard、Claim、Dossier、SkillSpec
  harness/         权限白名单、审批门控、出域检查与脱敏、预算/时限、限流、幂等、重试、审计
  skills/          data（AKShare、DeepSeek Search/Fetch）、compute（Decimal）、research（业绩复核 SOP）
  evidence/        证据工厂（快照+哈希）、清洗、去重聚类、分级、核验器
  graph/           LangGraph 主图、节点、运行器（人在环中断/恢复）、底稿渲染
  storage/         MongoDB：档案版本链、证据（只插入）、快照、任务、审计、缓存
  routing/         双轴路由（判别器 + 校准 + 拒判升级）
  experts/         专家规格、编排、首轮、质询、回应、主席
  memory/          版本差异与依赖传播
  evals/           质量指标、单 Agent vs 多专家对照、路由校准
  rsi/             RSI：ledger 账本、issues 坏案例、proposer 优化器、evaluator 评测器、gates 六道门控、runner 状态机、loader 运行时加载
  personal/        三期：用户确认档案（store）、个人情境官（officer，纯规则）
  watch/           三期：订阅与提醒存储（store）、扫描与增量复核（scanner）
  strategy/        四期：策略卡（models/store）、前向模拟盘（paper）、晋级门控（gates）、状态机（book）
  api/             FastAPI：app 组装 + 按业务拆分的路由（research、dossiers、evals、rsi、personal、watch、strategy）
  services.py      服务容器：API 与命令行共用的组装方式
  scheduler.py     后台定时：扫描订阅、推进模拟盘
  tracing.py       OpenTelemetry
  cli.py mcp_server.py
web/src/
  pages/           落地页、研究台、档案、任务、评测、自进化、订阅与复核、我的约束、策略与模拟盘
  components/      外壳（侧栏/问顾问/溯源抽屉）、RSI、个人情境、策略（规则编辑、净值图）等
evals/             golden/（计算、路由金标）、cases/（对照用例）
tests/             112 个测试（虚构数据 + 假模型，不联网；含 RSI 闭环、三期订阅/复核、四期模拟盘/晋级/回滚、API 冒烟）
```

## 已知限制

- 财报数值来自东方财富结构化数据，可能含追溯调整（已标注 `PIT 弱`）；公告只取标题，未解析 PDF 正文。
- 东财行情接口不稳定时自动回退新浪行情。
- 历史 as_of 只约束工具侧数据，无法消除模型预训练中的后验知识。
- 订阅扫描对「复核条件」只做关键词粗匹配，标为「可能触发」，需在复核时确认。
- 模拟盘按收盘价、整手、无手续费计算；只用于检验规则，不代表可实现收益。
- RSI 在真实数据上已发布两个版本：S1 经验库 v2（`rsi_d9c74b76`，新增 L-001）与 S3 检索模板 v2（`rsi_5221ba5e`，追加一个抓取站点），均过六道门控并人工批准（单人阶段标「自批」）；档案 600519 v6 记录使用了经验库 v2。回滚由测试覆盖。
