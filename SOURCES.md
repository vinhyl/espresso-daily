# 信息源头清单（规划期 / Planning Source List）

> 用途：为「意式浓缩日报」自动采集管线提供信息源。
> 设计原则（按用户要求）：
> 1. **统一信息流** —— 网站不分板块，所有 espresso 相关内容汇入一条每日流；
> 2. **动态标签** —— 由 LLM/规则在整理时为每条内容生成 2-5 个**开放、具体**的主题标签
>    （如 `9-bar`、`水温`、`研磨度`、`布粉wdt`、`预浸泡`、`咖啡机`、`磨豆机`、`新手`、`评测`…），
>    标签词表随内容动态生长；网站不做固定三分类，标签仅作为**可筛选标签**存在；
> 3. `category_hint` 只是 LLM/回退的**弱提示**，不决定最终标签。
>
> **当前状态（2026-08，管线实测前）**：
> - `content/` 现有 27 篇条目为 **demo 演示数据**（临时为 demo 服务），**不是管线真实产出**。
>   真实内容需待管线实测（开启 LLM + 抓取）后由 `content/YYYY-MM-DD-NN.md` 流水线落盘。
> - 标签处于**观察期**：`[ui].show_tags = false`，标签页与标签 chips 不在 UI 展示（机制保留，
>   待实测观察标签生成质量后再决定是否开启；**勿擅自开启**）。本清单中的标签设计原则是长期目标，非当前 UI 状态。
>
> 验证状态图例：✅ 手测可用（demo 期单次验证） · ⚠️ 需特殊处理 · ❓ 待验证

---

## A. RSS 资讯 / 博客源（英文为主，标准 RSS，直接可用）

| # | 名称 | Feed URL | 覆盖内容 | 状态 |
|---|------|----------|----------|------|
| A1 | **Sprudge** | `https://sprudge.com/feed` | 咖啡新闻、文化、器具(Gear)、城市指南、厂商动态 | ✅ 手测（demo 期, RSS 2.0） |
| A2 | **Perfect Daily Grind** | `https://perfectdailygrind.com/feed/` | 全产业链：产地、烘焙、行业、冲煮、espresso 专题 | ✅ 手测（demo 期） |
| A3 | **Daily Coffee News** | `https://dailycoffeenews.com/feed/` | 行业商业新闻、新品、市场 | ✅ 手测（demo 期） |
| A4 | **Barista Hustle** | `https://www.baristahustle.com/blog/feed/` | 专业技术、萃取科学、培训、配方 | ⚠️ Cloudflare 防护，需带浏览器 UA / 代理 |
| A5–A11 | Coffee Review / European Coffee Trip / Coffeeness / Bean Ground / Jimseven 等 | 站点 `/feed` | 评测、教程、百科 | ❓ 待逐个验证 RSS |

> 接入方式：`config.toml` 里 `type="rss"` 即可，`fetch.py` 用 `feedparser` 解析，
> 去重按 `link`（空 `link` 回退按 `title`，见 `fetch_all`；实测中若发现跨源转载重复，可再补 `pubDate+title` 去重）。

## B. 社区 / 论坛

| # | 名称 | 地址 / Feed | 覆盖内容 | 状态 |
|---|------|-------------|----------|------|
| B1 | **Reddit r/espresso** | `https://www.reddit.com/r/espresso/.rss` | 60 万+ 成员，每日调参、器具讨论、问题排查 | ✅ 手测（demo 期, 标准 `.rss`） |
| B2 | **Home-Barista.com Forums** | phpBB 自带 `https://www.home-barista.com/feed.php`（或 `/forums/feed.php?mode=topics`） | 硬核技术、机器/磨豆机深度评测 | ⚠️ 站点防护，需浏览器 UA，或经 RSSHub 的 `nodebb`/论坛路由 |
| B3/B4 | Coffee Forums / CoffeeSnobs | 站点 `/feed` | 器具、配件讨论 | ❓ 待确认 RSS |

## C. 视频 / 社媒专家（无 RSS，作为 LLM 整理的「权威参照」而非自动抓取）

- **James Hoffmann**、**Lance Hedrick**、**Whole Latte Love**（YouTube）—— 权威萃取方法论、器具评测。
- 用途：LLM 评分阶段可把这些作为高权重「权威信源」参照；不自动抓取。B站/小红书对应 UP 主同理。

> 这些权威参照现已结构化沉淀到项目内的 **`knowledge/` 基础/常青知识库**（每主题一篇、跨多篇综合、末尾列全源），
> 并在管线解读新闻时作为背景上下文注入 LLM，生成带出处的「深度解读」。详见 README 的「基础 / 常青知识库」一节。

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

## 限流与礼貌

- 每源抓取间隔 ≥ 数秒（`[fetch] per_source_delay`），设置 `User-Agent`，尊重 `robots.txt`。
- RSSHub 自带缓存，不会对被源站造成压力；直连搜索接口请务必限流。
- demo 期手测：Sprudge / Perfect Daily Grind / Daily Coffee News / Reddit `.rss` 均可直接抓取成功
  （单次验证，生产稳定性待管线实测确认）。
