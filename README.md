# ESPRESSO DAILY · 意式浓缩每日资讯流

一个**每日更新**的意式浓缩咖啡（espresso）内容资讯站：

- **统一信息流**：所有 espresso 相关内容汇入一条每日流（不分板块）。
- **动态标签（非固定分类）**：由 LLM 为每条内容生成 2-5 个**开放、具体**的主题标签
  （如 `9bar`、`水温`、`研磨度`、`布粉WDT`、`预浸泡`、`咖啡机`、`磨豆机`、`新手`、`评测`…），
  标签词表随内容动态生长；网站不做固定三分类，标签仅作**可筛选标签**。
- **采集管线**：RSS + 权威社区 → LLM 质量评估与整理 → 按日期落盘 `content/` → 静态生成 `public/`。
- **筛选机制**：动态标签多选筛选（按词频渲染 chips）+ 按月份折叠的日期归档 + 关键词搜索，状态可用 URL hash 分享。
- **部署**：静态站，部署到 **Cloudflare Pages**（免费套餐）。

信息源清单见 [SOURCES.md](SOURCES.md)。

---

## 视觉设计规范（Design System）

本站的视觉语言为 **「现代精致亮调工业风 · 咖啡」**：以微水泥暖白铺底、灰泥浅灰做卡片层次，用 1px 哑光铸铁黑线框划分几何区域（弃用重阴影），并以庄园绿作克制点缀；全站叠加细微噪点纹理模拟水泥微粒质感，顶部导航采用磨砂玻璃悬浮。设计细节见 [overview.md](overview.md)。

### 配色（70 / 20 / 10 分配）

| 角色 | Token | 值 | 用途 |
|---|---|---|---|
| 主背景 | `--bg-main` | `#F4F3EF` 微水泥暖白 | 全站底色（70%） |
| 卡片 / 模块 | `--bg-surface` | `#E6E4DF` 灰泥浅灰 | 卡片、侧栏、规格面板（20%） |
| 主文字 / 线框 | `--text-primary` | `#2B2A28` 哑光铸铁黑 | 标题、正文、1px 结构线框 |
| 副文字 / 线 | `--text-secondary` | `#8C8881` 石墨中灰 | 副标题、分割线、非激活态（规范原值） |
| 弱文字 | `--text-muted` | `#67615A` | 小号元信息 / 面包屑（AA 安全变体） |
| 品牌点缀 | `--accent` | `#8A9A86` 庄园绿 | CTA 按键、评分 gauge、选中态、hover |
| 悬停加深 | `--accent-hover` | `#73836F` | 按钮 hover 压暗 |
| 高亮微酸绿 | `--accent-bright` | `#AACC00` | 仅用于小色块 / 点（信号点、强调块） |

> 绿色面积越集中越克制，高级感越强：**大面积填充只用庄园绿 `#8A9A86`，酸绿 `#AACC00` 只点缀小块**。

### 材质与触感

- **细微噪点（Noise）**：主背景与卡片背景叠加约 4.5% 透明度的去饱和 SVG 噪点，赋予类似高档艺术纸 / 水泥微粒的柔和质感。
- **磨砂玻璃（Backdrop Blur）**：顶部 `masthead` 悬浮导航使用 `rgba(244,243,239,0.72)` + `backdrop-filter: blur(12px)`，底层绿色滑过时产生精致模糊扩散。

### 字体

- 标题 / 大数字：**Space Grotesk**（工业无衬线）
- 正文：**IBM Plex Sans**
- 数据 / 规格 / 标签：**IBM Plex Mono**
- 中文：**Noto Sans SC**

### 质感法则（四重结合）

1. **底座**：带噪点的微水泥暖白铺底；
2. **骨架**：1px 铸铁黑细线划分几何区域，**不使用重阴影**，保持扁平工业切割感；
3. **点缀**：在按键与关键信息处集中施加庄园绿；
4. **浮层**：顶部磨砂玻璃，带来现代通透感。

### 可访问性（已实测对比度）

- 小号弱文字用 `--text-muted #67615A`，在主底 / 卡底均为 AA（≈5.5 / 4.8 :1）；
- CTA 按钮默认庄园绿 `#8A9A86` + 铸铁黑字（≈4.8:1，AA）；hover 按设计压暗到 `#73836F`（暗字约 3.6:1，低于正文 AA，但仅作「压暗」微反馈且带 1px 黑边框兜底，已与产品确认保留）；
- 副标题 `#8C8881` 按规范原值保留（约 3:1），如需严格合规可加深一档；
- 全站交互元素含 `:active` 按下态与 `:focus-visible` 焦点环，并尊重 `prefers-reduced-motion`。

### 按钮体系（三级 + 预留位）

- **主 CTA** `.btn-ghost`：庄园绿填充，页面级主行动（如 hero「最新日报」），全站唯一；
- **导航次级** `.btn-outline`：透明底 + 铁灰描边，顶部工具按钮（如「查看归档」）；
- **轻量入口**：文本链接 + 绿箭头（today-strip / dcard 列表内）。
- **预留位**：`.btn-icon`（RSS 订阅）与 `.lang-switch`（中/EN 语言切换）样式已备、模板中注释隐藏，待 feed.xml 生成与英文版上线后启用。详见 [overview.md](overview.md) 的「按钮体系」。

### 关于标签（重要约束）

当前为**观察期**，`config.example.toml` 的 `[ui].show_tags = false`，**标签页与标签 chips 不展示**（构建输出 `tags: 0`）。视觉规范中所有标签相关样式均已预留但默认不渲染；改回 `true` 才会显示，勿擅自开启。

---

## 目录结构

```
src/
  content_loader.py   解析 content/*.md（frontmatter + Markdown）→ 结构化条目
  build.py            静态站生成器（Jinja2）→ public/（含动态标签页）
  fetch.py            抓取 RSS / 搜索接口（feedparser + httpx + 搜索适配器）
  score.py            LLM 评估/动态打标签 + 分级内容处理（kind 分流，两阶段，见下）
  knowledge.py        基础/常青知识库加载与背景上下文拼接（私有，不参与建站）
  pipeline.py         串联 fetch → score(注入知识库) → 写 content → build
  templates/          layout / index / day / tag / macros
assets/               style.css（现代工业/精致风）、app.js（动态标签筛选）
content/              每日条目（Markdown，流水线或手写；可含「深度解读」区块）
knowledge/            基础/常青知识库（私有，每主题一篇多源综合，不参与建站）
public/               构建产物（Cloudflare Pages 输出目录）
scripts/new_day.py    新建一日空白模板
scripts/new_knowledge.py  新建一个常青主题模板
config.example.toml   配置示例（信息源 / LLM / 标签 / 知识库）
.github/workflows/    每日定时管线
```

## 本地使用

```bash
# 1. 准备环境（Python 3.11+）
python -m venv .venv && source .venv/bin/activate
pip install jinja2 markdown feedparser httpx python-dotenv

# 2. 仅生成静态站（用现有 content/）
python -m src.build --config config.example.toml

# 3. 本地预览
python -m http.server 3000 --directory public
# 打开 http://localhost:3000
```

## 每日更新机制

两种方式任选：

**A. 手写 / 脚手架（默认，无需 API）**
```bash
python scripts/new_day.py                 # 今天空白模板
python scripts/new_day.py 2026-08-03     # 指定日期
# 编辑 content/ 下的 .md，再 python -m src.build
```

**B. 自动管线**
```bash
cp config.example.toml config.toml       # 按需开启 LLM、调整信息源
# 在 .env 配置 ESPRESSO_LLM_API_KEY（OpenAI 兼容，如 DeepSeek）
python -m src.pipeline                   # 抓取 → 评估 → 写 content → 构建
python -m src.pipeline --dry-run         # 只预览将收录的内容
```
- 标签由 LLM 动态生成（2-5 个具体主题标签）；未启用 LLM 时按关键词词典规则回退打标签。
- 去重：同一 `source_url` / 标题不重复收录。

**C. 定时自动化（推荐）**
`.github/workflows/daily.yml` 每天 **00:40 (UTC+8)**（cron `40 16 * * *` UTC）运行管线并提交 `content/` 与 `public/`，推送即触发部署。在仓库 Secrets 配置 `ESPRESSO_LLM_API_KEY` 即可启用 LLM（workflow 通过环境变量 `ESPRESSO_LLM_ENABLED=true` 强制开启，无需改 config；未配置 key 时自动回退规则评分）。

> **时区与归档**：日报以国内用户为主，**所有文章统一按北京时间（Asia/Shanghai / GMT+8）归档**。
> `fetch.py` 把 RSS 的 UTC 发布时间先转换到北京时间再截日，避免 Reddit / Sprudge 等海外源
> 在北京时间当天凌晨（对应 UTC 前一天傍晚至深夜）发布的内容被错归到「昨天」
> （详见代码注释与 `config.example.toml` 的 `[fetch].timezone`）。该归档时区**不影响定时任务**——
> workflow 的 cron 用 UTC 书写，换算见 `.github/workflows/daily.yml` 注释。

## 部署到 Cloudflare Pages

推荐（最稳）：流水线已生成 `public/` 并提交，Cloudflare Pages 选择 **Git 集成 → 构建命令留空 → 输出目录 `public/`**，推送即发布。

或让 CF 构建：构建命令 `pip install jinja2 markdown feedparser httpx python-dotenv && python -m src.build --config config.example.toml`，输出目录 `public/`。

> **构建次数（免费版 500 次/月）注意**：Cloudflare Pages 免费版每月最多 500 次构建，每次 `git push` 触发一次。
> - 站点生成的文件是「`index.html` + 每个日期 1 个 `days/` 页 + 每个标签 1 个 `tags/` 页」，**文章本身不单独占文件**，因此文章数量不会触及 20,000 文件上限（免费版够用几十年）。
> - **务必按天聚合构建**：管线/定时任务应把一天内采集到的多条内容合并成**一次 commit + 一次 push**（即每日重建一次），而不是「来一篇就 push 一次」。后者一天几十篇会迅速逼近 500 次/月的限制。
> - 纯文本站构建耗时仅毫秒级，远低于 20 分钟构建超时；带宽与静态请求在免费版均为无限。
> - 若日后改为「每篇文章单独成页」，文章数≈文件数，约 2 万篇后需升级 Pro（$20/月，文件上限 10 万）。

## 内容格式

`content/YYYY-MM-DD-xx.md`：

```markdown
---
date: 2026-08-02
title: 标题
source: 来源名（可选）
source_url: https://（可选）
tags: 9bar, 水温, 萃取率tds, 意式基础   # 2-5 个具体主题标签，逗号分隔
score: 85                             # 0-100 质量分（管线落盘；手写可选）
kind: deepdive                        # 内容处理方式：as-is/translate/summary/deepdive（管线落盘）
---

正文用 Markdown。要点、原理、参考链接…
```

标签是**动态**的：手写时自由给每条打 2-5 个具体标签（如 `9bar`/`水温`/`研磨度`/`咖啡机`/`新手`/`评测`）；
接入 LLM 后由模型自动生成，词表不固定。构建期会汇总全站标签词频，前端据此动态渲染筛选 chips 与标签页。

> **当前为观察期**：标签的**展示与生成已通过 `config.example.toml` 的 `[ui].show_tags = false` 暂时关闭**——
> 现有标签生成机制较粗糙、标签过多且无实际意义。待采集一段时间、明确标签的必要性后再评估机制，
> 改回 `true` 即可恢复；`content/*.md` 中的 `tags` 数据字段保留不动，不受影响。

## 分级内容处理（kind 分流）

管线对每条内容分**两阶段**处理（LLM 启用时，见 `src/score.py` 模块注释）：

- **阶段一（轻量评估，不注入知识库）**：LLM 一次性输出 `tags` / `summary`（处理后正文）/ `score` / `kind`。
- **阶段二（仅 `kind=deepdive` 的内容）**：注入常青知识库生成「深度解读」区块，由 `[llm].deepdive_enabled` 总开关控制。

`kind` 四值决定了「正文」怎么来：

| kind | 适用情况 | 正文产出 |
|---|---|---|
| `as-is` | 中文精炼原文 | 原文直出，不做摘要/改写 |
| `translate` | 英文等非中文精炼原文 | 翻译成中文直出，不压缩不精炼 |
| `summary` | 原文冗长/信息密度低 | 精炼中文摘要 |
| `deepdive` | 原理性强/反常识/信息密度高 | 精炼中文摘要 + 「深度解读」区块 |

简单资讯（简讯/新品发布等）不会被强行深度解读；`score < min_score` 的内容照旧不收录。
单日页标题按当天实际含深度解读的篇数动态显示（无解读时不显示该文案）。

## 每日总标题（headline）

每条日报在**归档列表**与首页「**近期日报**」卡片上显示的标题，由 LLM 对当天全部已收录资讯
生成的**概括性总结**（可聚焦最重大的一条，也可综合最多 2 条相关资讯，建议 15-40 字）：

- **生成**：管线在逐条评估（阶段一/二）之后，把当天已收录条目（title + 摘要 + 评分）按评分降序
  批量发给 LLM 生成，落盘为 `content/{date}-00.md`（frontmatter 带 `kind: headline`，
  `title`/`headline` 同存总标题文本，正文留空）。`-00.md` 与普通条目 `-01.md..N` 不冲突，
  已存在则跳过生成（幂等，可手工编辑微调）。
- **开关**：`[llm].headline_enabled = true`（在 `llm.enabled` 基础上额外控制）；
  未启用 / LLM 不可用 / 生成失败时，**不写文件**，构建期回退「当日最高分条目标题」（旧行为）。
- **超长保护（软/硬双阈值）**：生成结果超过软阈值 `headline_soft_chars`（默认 60）时，
  自动把长标题回传给 LLM 压缩一次（保留核心信息）；压缩后仍超过硬阈值 `headline_max_chars`
  （默认 100）才丢弃并回退最高分条目标题。阈值可在 `config.example.toml` 调整。
- **隔离**：headline 文件不参与条目统计、单日页渲染与去重键，只被构建期
  `load_day_headlines()` 读取供归档/首页使用。

## 基础 / 常青知识库（深度解读的来源）

网站只展示「每日资讯流」（`content/`）。另有 **`knowledge/`** 作为**私有**的权威知识库：

- **定位**：每个主题一篇，是对**多篇权威文章的综合**（而非搬运单篇），正文末尾用「`## 参考来源`」列出该主题涉及的**全部源头**。例如 `9bar`、`通道效应`、`萃取率tds`、`布粉wdt`、`预浸泡`、`水温`、`研磨度`、`填压`、`粉水比` 等。
- **不直接上站**：`build.py` 只加载 `content/`，完全不碰 `knowledge/`，因此常青库天然不出现在公开站点上。
- **怎么用**：管线只对 `kind=deepdive` 的新闻（阶段二）把整库（或小库默认的「全量注入」，见 `config.example.toml` 的 `[knowledge]`）作为背景上下文注入 LLM，并要求 AI **不要简单复述新闻**，而是结合背景从原理/操作/器具/对比/误区等角度做**多角度深度整理**，且在引用某个知识点时**注明其权威来源**。生成的内容里会带一个独立的「深度解读」区块。
- **维护**：`python scripts/new_knowledge.py "9 bar 水压"` 生成主题模板；人工补充/校订综合内容与来源即可。库体量不大时保持 `mode = "all"` 最全面；若日后库变大，可切 `mode = "recall"`（按标签/概念高召回）以控 token。
- **无 LLM 时**：走规则回退，正文取抓取摘要/标题，不产出「深度解读」区块（翻译与深度解读均依赖 LLM）。
