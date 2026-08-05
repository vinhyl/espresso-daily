# 信息源头清单（规划期 / Planning Source List）

> 用途：为「意式浓缩日报」自动采集管线提供信息源。
> 设计原则（按用户要求）：
> 1. **统一信息流** —— 网站不分板块，所有 espresso 相关内容汇入一条每日流；
> 2. **动态标签** —— 由 LLM/规则在整理时为每条内容生成 2-5 个**开放、具体**的主题标签
>    （如 `9-bar`、`水温`、`研磨度`、`布粉wdt`、`预浸泡`、`咖啡机`、`磨豆机`、`新手`、`评测`…），
>    标签词表随内容动态生长；网站不做固定三分类，标签仅作为**可筛选标签**存在；
> 3. `category_hint` 是 LLM/回退的**弱提示**（不决定最终标签），**同时**也作为来源配额的分层依据（见下方「来源配额」）。
>
> **当前状态（2026-08）**：
> - 初始化时灌入的 demo 种子内容（`content/` 2026-07-28~08-02，共 30 篇）已于 2026-08-05 清理；`knowledge/` 保留。
> - `content/` 现由每日管线真实产出（落盘为 `content/YYYY-MM-DD-NN.md`，已含 08-03 / 08-04 / 08-05 等日期）。
> - 标签处于**观察期**：`[ui].show_tags = false`，标签页与标签 chips 不在 UI 展示（机制保留，
>   待实测观察标签生成质量后再决定是否开启；**勿擅自开启**）。本清单中的标签设计原则是长期目标，非当前 UI 状态。
>
> 验证状态图例：✅ 手测可用（demo 期单次验证） · ⚠️ 需特殊处理 · ❓ 待验证

---

## A. RSS 资讯 / 博客源（英文为主，标准 RSS，直接可用）

| # | 名称 | Feed URL | 覆盖内容 | 状态 |
|---|------|----------|----------|------|
| A1 | **Sprudge** | `https://sprudge.com/feed` | 咖啡新闻、文化、器具(Gear)、城市指南、厂商动态 | ✅ 手测；**降为低频文化信号源**（industry，每期≤1，关键词过滤） |
| A2 | **Perfect Daily Grind** | `https://perfectdailygrind.com/feed/` | 全产业链：产地、烘焙、行业、冲煮、espresso 专题 | ✅ 手测；**降为补充源**（industry，仅收豆种/烘焙/供应链变化，关键词过滤） |
| A3 | **Daily Coffee News** | `https://dailycoffeenews.com/feed/` | 行业商业新闻、新品、市场 | ✅ 手测；**强化意式过滤**（industry，仅设备/浓缩/奶咖自动化/商用工作流，关键词过滤） |
| A4 | **Barista Hustle** | `https://www.baristahustle.com/feed/`（`/blog/feed/` 实测 403，已改根路径） | 专业技术、萃取科学、培训、配方 | ✅ 已修复并启用（tech_experiment，差异化技术源） |
| A5 | **Coffee Ad Astra** | `https://coffeeadastra.com/feed/` | 专家实验与建模（Espresso/Extraction/Physics） | ✅ 新增（tech_experiment，须关键词二次过滤，剔除纯滤泡内容） |
| A6 | **CoffeeGeek** | `https://coffeegeek.com/feed/` | 独立设备评测 | ✅ 新增（independent_review，每期≤1） |
| A7 | **Whole Latte Love** | `https://www.wholelattelove.com/blogs/tech-tips.atom` | 品牌教程/评测 | ✅ 新增（tutorial，与 Clive 合计每期≤1） |
| A8 | **Clive Coffee** | `https://www.clivecoffee.com/blogs/learn.atom` | 品牌教程/评测 | ✅ 新增（tutorial，与 WLL 合计每期≤1） |
| A9–A15 | Coffee Review / European Coffee Trip / Coffeeness / Bean Ground / Jimseven 等 | 站点 `/feed` | 评测、教程、百科 | ❓ 待逐个验证 RSS（候选扩充） |

> 接入方式：`config.toml` 里 `type="rss"` 即可，`fetch.py` 用 `feedparser` 解析，
> 去重按 `link`（空 `link` 回退按 `title`，见 `fetch_all`；实测中若发现跨源转载重复，可再补 `pubDate+title` 去重）。

### 来源配额（`category_hint` 分层，阶段一 1.3）

`pipeline.py` 按每条来源的 `category_hint` 把内容归入以下**层级**，并对每层设每期上限；
同时支持 `max_per_source`（单源上限）与 `quota_group`+`max_per_group`（多源合计上限）。
最终总数再受 `[llm].max_per_day` 硬上限约束（默认 12，宁缺毋滥）。

| 层级（category_hint） | 含来源 | 每期上限 |
|---|---|---|
| `tech_experiment`（技术实验） | Barista Hustle、Coffee Ad Astra | 2 |
| `independent_review`（独立测试） | CoffeeGeek | 1 |
| `tutorial`（专业教程） | Whole Latte Love、Clive Coffee | 1（两源合计，靠 `quota_group=gear_tutorials` 约束） |
| `industry`（行业媒体） | Daily Coffee News、Perfect Daily Grind、Sprudge | 2 |
| `community`（社区） | Reddit r/espresso | 2 |
| `official`（官方公告） | （暂无专源，事件触发） | 不硬限 |

> 选稿逻辑（`_apply_quota`）：先按评分降序、社区类再按互动量（赞/评论）排序，
> 再贪心填充——任一层/源/组达到上限即停止该档位的收录。未知 `category_hint` 归入 `industry`。

### 源级关键词二次过滤（`include_any` / `exclude_any`）

每个 `[[sources]]` 可带 `include_any`（标题+摘要至少命中其一，意式相关性闸门）与
`exclude_any`（命中任一即丢弃，如晒图/购买咨询/健康/公平贸易），在 `fetch_all` 内于
LLM 评估**之前**执行，避免把无关内容送进稀缺的 LLM/算力。详见 `config.example.toml` 各源配置。

### 全文抓取白名单（`full_text`）

白名单来源（A4 Barista Hustle、A5 Coffee Ad Astra、A6 CoffeeGeek、A3 Daily Coffee News、A7 Whole Latte Love、A8 Clive Coffee）在 config 里标了 `full_text = true`。管线仅在**初筛 `accept` 之后**才对这些源抓原文全文做精评——全文是稀缺资源（有流量与封禁成本），避免基于截断 RSS 摘要虚构参数与结论。成本闸门见 `config.example.toml` 的 `[fetch].fulltext_*`（每运最大篇数 / 间隔 / 超时）。详见 README「编辑判断管线 → 按需全文抓取」。

## B. 社区 / 论坛

| # | 名称 | 地址 / Feed | 覆盖内容 | 状态 |
|---|------|-------------|----------|------|
| B1 | **Reddit r/espresso** | `https://www.reddit.com/r/espresso/top/.rss?t=week` | 60 万+ 成员，每日调参、器具讨论、问题排查 | ✅ 手测；**降级为社区补充**（community，改取 top 周榜，赞/评论作排序信号，每期≤2，关键词过滤晒图/求推荐） |
| B2 | **Home-Barista.com Forums** | phpBB 自带 `https://www.home-barista.com/feed.php`（或 `/forums/feed.php?mode=topics`） | 硬核技术、机器/磨豆机深度评测 | ⚠️ 站点防护，需浏览器 UA，或经 RSSHub 的 `nodebb`/论坛路由 |
| B3/B4 | Coffee Forums / CoffeeSnobs | 站点 `/feed` | 器具、配件讨论 | ❓ 待确认 RSS |

## C. 视频 / 社媒专家（无 RSS，作为 LLM 整理的「权威参照」而非自动抓取）

- **James Hoffmann**、**Lance Hedrick**、**Whole Latte Love**（YouTube）—— 权威萃取方法论、器具评测。
- 用途：LLM 评分阶段可把这些作为高权重「权威信源」参照；不自动抓取。B站/小红书对应 UP 主同理。

> 这些权威参照现已结构化沉淀到项目内的 **`knowledge/` 基础/常青知识库**（每主题一篇、跨多篇综合、末尾列全源），
> 并在管线解读新闻时作为背景上下文注入 LLM，生成带出处的「深度解读」。详见 README 的「基础 / 常青知识库」一节。
> 知识库亦含科研综述向条目（如意式渗流物理），由周级学术雷达的补丁机制持续追加。

## D. 中文源（**重点：非 RSS 怎么接**）

| # | 名称 | 覆盖内容 | 推荐接入方式 |
|---|------|----------|--------------|
| D1 | **咖啡沙龙** | 中文权威社区、深度科普与评测 | RSSHub（`/coffeesalon/...`，如有社区路由）或人工精选 |
| D2 | **什么值得买 · 咖啡** | 器具购买经验、性价比评测 | RSSHub 的 `/smzdm/keyword/咖啡` 路由，或人工精选 |
| D3 | **知乎**「咖啡 / 意式浓缩」 | 深度科普、原理讲解 | **RSSHub** `/zhihu/search/意式浓缩` 或 `type=search`(parser=zhihu) |
| D4 | **豆瓣** 咖啡小组 | 生活化分享、器具交流 | **RSSHub** `/douban/group/<小组id>` |
| D5 | **B站** 咖啡 UP 主 | 视频教程、器具开箱 | **RSSHub** `/bilibili/search/all/意式浓缩咖啡` 或 `type=search`(parser=bilibili) |
| D6 | **小红书** | 图文教程、开箱 | 反爬严格，建议人工精选（或 RSSHub 社区路由） |

---

## 非 RSS 源接入操作指南（具体怎么操作）

非 RSS 源有三条落地路径，**推荐优先用 RSSHub**（把一切归一化成 RSS，管线上只需一套 `rss` 逻辑）。

### 路径 1：自托管 RSSHub（最省心，推荐）

把所有无 RSS 的站点先转成 RSS，再在 `config.toml` 里按 `type="rss"` 接入。

```bash
# 1) 启动 RSSHub（Docker，一行命令）
docker run -d --name rsshub -p 1200:1200 diygod/rsshub

# 2) 在 config.toml 里把下面条目的 enabled 改为 true，并把 127.0.0.1:1200 换成你的地址
[[sources]]
name = "知乎 · 意式浓缩"
type = "rss"
url = "http://127.0.0.1:1200/zhihu/search/%E6%84%8F%E5%BC%8F%E6%B5%93%E7%BC%A9"   # 中文直接写也行
category_hint = "mixed"
lang = "zh"
enabled = true
```

常用 RSSHub 路由（官方路径，稳定）：

| 站点 | RSSHub 路由（拼在 RSSHub 基址后） |
|------|-----------------------------------|
| 知乎搜索 | `/zhihu/search/:keyword` |
| B站搜索 | `/bilibili/search/all/:keyword` |
| 豆瓣小组 | `/douban/group/:id` |
| 什么值得买 | `/smzdm/keyword/:keyword` |

> 不想自建也可用公共 RSSHub 实例，但公共实例常被限流/屏蔽（本机实测 `rsshub.app` 返回 403），
> 生产环境**强烈建议自托管**。RSSHub 也支持缓存、定时、访问控制，详见 https://docs.rsshub.app 。

### 路径 2：直连搜索接口（`type="search"`，无需 RSSHub，但需维护）

`fetch.py` 已内置 `zhihu / bilibili / smzdm` 三个 JSON 搜索适配器，把结果归一化成统一条目。
> 注意：当前 `config.example.toml` 中「什么值得买」以 `type="manual"` 人工精选接入（适配器已备好但未启用，
> 实测时如需自动抓取，改 `type="search"` + `parser="smzdm"` 即可）。
配置示例（知乎）：

```toml
[[sources]]
name = "知乎搜索 · 意式浓缩"
type = "search"
parser = "zhihu"     # 对应内置适配器
url = "https://www.zhihu.com/api/v4/search_v3?t=general&q=%E6%84%8F%E5%BC%8F%E6%B5%93%E7%BC%A9&limit=20"
referer = "https://www.zhihu.com/"
lang = "zh"
enabled = true
```

> 注意：知乎/B站 有反爬（本机实测直连会被拦），稳定性不如 RSSHub。新增站点只需在
> `fetch.py` 的 `SEARCH_PARSERS` 里加一个解析函数即可，结构统一。

### 路径 3：人工精选（`type="manual"`）

对反爬最严（小红书）或质量优先的场景：

```bash
# 生成某天的内容脚手架（含 frontmatter 模板）
python -m scripts.new_day 2026-08-03
```

然后手动把选中的文章写成 `content/2026-08-03-*.md`（Markdown + frontmatter），
LLM/规则阶段会自动为它们打上动态标签。

---

## E. 学术源（每周学术雷达，type=academic）

每周学术雷达专用，由 `weekly.yml` 周级 CI 抓取，**不进每日 `content/`**。在 `config.example.toml` 里 `type="academic"`、`enabled=false`（专为周级 CI 服务；`enabled=false` 确保每日管线不会把它误抓进每日站点流）。

| 名称 | 检索方式 | 覆盖内容 | 状态 |
|---|---|---|---|
| **Espresso Extraction (OpenAlex + Crossref)** | `academic_must=["espresso","extraction"]`（严格 AND）+ `academic_exclude`（tea / cold brew / sensory / consumer…）+ `academic_filters`（如 `from_publication_date:2015-01-01`） | 意式萃取同行评审论文、预印本；Crossref 补全 DOI/期刊 | ✅ 新增（严格 AND + 咖啡领域消歧，剔除 ESPReSSO 单点登录、cembalo 乐器等缩写歧义） |

检索细节与消歧规则、研究卡字段、知识库补丁机制见 README「每周学术雷达（阶段三）」。产物落点：`research/`（研究卡+周报，周级 CI 提交）、`knowledge/patches/`（补丁提案，未应用不入库）、`reports/`（抽检清单，gitignore）。

## 限流与礼貌

- 每源抓取间隔 ≥ 数秒（`[fetch] per_source_delay`），设置 `User-Agent`，尊重 `robots.txt`。
- RSSHub 自带缓存，不会对被源站造成压力；直连搜索接口请务必限流。
- demo 期手测：Sprudge / Perfect Daily Grind / Daily Coffee News / Reddit `.rss` 均可直接抓取成功
  （单次验证，生产稳定性待管线实测确认）。
