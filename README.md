# ESPRESSO DAILY · 意式浓缩每日资讯流

一个**每日更新**的意式浓缩咖啡（espresso）内容资讯站：

- **统一信息流**：所有 espresso 相关内容汇入一条每日流（不分板块）。
- **动态标签（非固定分类）**：由 LLM 为每条内容生成 2-5 个**开放、具体**的主题标签
  （如 `9bar`、`水温`、`研磨度`、`布粉WDT`、`预浸泡`、`咖啡机`、`磨豆机`、`新手`、`评测`…），
  标签词表随内容动态生长；网站不做固定三分类，标签仅作**可筛选标签**。
- **采集管线**：RSS + 学术源 → ① 源级关键词预筛 → ② LLM 初筛（拒非意式/纯展示/广告等）→ ③ 白名单源按需全文抓取 → ④ 六维可解释评分 → ⑤ 48h 同题聚类 → ⑥ 知识库深度解读（仅 `deepdive`）→ 落盘 `content/` → 静态生成 `public/`。学术雷达为**独立周级管线**，产出 `research/` 与知识库补丁，不进每日站点流。
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
  fetch.py            抓取 RSS / 搜索接口 / 学术源；按需全文抓取；源级关键词预筛；抓取失败结构化记录
  score.py            初筛 prescreen + 六维可解释评分 + 内容性质(content_type) + 48h 事件聚类 + 动态标签 + 分级(kind) + 深度解读
  knowledge.py        基础/常青知识库加载与背景上下文拼接（私有，不参与建站）
  pipeline.py         串联 fetch → 初筛 → 全文 → 六维精评 → 去重 → 聚类 → 配额 → 写 content → build → 质量报告落盘
  academic.py         每周学术雷达：抓论文 → 建研究卡 → 知识库补丁提案 → 周报 + 抽检清单（独立周级 CI）
  quality_report.py   每源候选/入选/拒绝/平均分 + 来源占比/重复率/意式核心占比 + 抓取失败维度，落 reports/
  templates/          layout / index / day / tag / macros
assets/               style.css（现代工业/精致风）、app.js（动态标签筛选）
content/              每日条目（Markdown，流水线或手写；可含「深度解读」区块）
research/             每周学术雷达研究卡（周级 CI 提交到仓库，不参与建站；供人工抽检）
knowledge/            基础/常青知识库（私有，每主题一篇多源综合）；patches/ 子目录存补丁提案（未应用前不入库）
public/               构建产物（Cloudflare Pages 输出目录）
reports/              运行时产物（质量报告、抓取失败清单、抽检清单；gitignore，不提交）
scripts/new_day.py    新建一日空白模板
scripts/new_knowledge.py  新建一个常青主题模板
config.example.toml   配置示例（信息源 / LLM / 标签 / 知识库 / 学术源）
.github/workflows/    每日定时管线（daily.yml）+ 每周学术雷达（weekly.yml）
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
python -m src.pipeline                   # 预筛 → 初筛 → 全文(白名单) → 六维评分 → 聚类 → 配额 → 写 content → 构建 → 质量报告
python -m src.pipeline --dry-run         # 只预览将收录的内容（不写 content/、不产生质量报告文件）
```
- 管线内置三级编辑判断（见「编辑判断管线」一节）：源级预筛 → LLM 初筛 → 六维评分；`min_score=60` 以下不收录。
- 标签由 LLM 动态生成（2-5 个具体主题标签）；未启用 LLM 时按关键词词典规则回退打标签。
- 去重：同一 `source_url` / 标题不重复收录；同题事件经 48h 聚类折叠为 `related`。

**C. 定时自动化（推荐）**
`.github/workflows/daily.yml` 每天 **00:40 (UTC+8)**（cron `40 16 * * *` UTC）运行管线并提交 `content/` 与 `public/`，推送即触发部署。在仓库 Secrets 配置 `ESPRESSO_LLM_API_KEY` 即可启用 LLM（workflow 通过环境变量 `ESPRESSO_LLM_ENABLED=true` 强制开启，无需改 config；未配置 key 时自动回退规则评分）。

**D. 每周学术雷达（独立周级 CI）**
```bash
python -m src.academic                  # 抓 OpenAlex+Crossref → 建研究卡 → 补丁提案 → 周报 + 抽检清单（写 research/、knowledge/patches/、reports/）
python -m src.academic --date 2026-08-04   # 指定运行日期
python -m src.academic apply knowledge/patches/2026-08-04-xxx.json   # 应用一条知识库补丁（并入 knowledge/）
```
- 由 `.github/workflows/weekly.yml` 周一级触发（周一 17:10 UTC），与每日管线解耦，不会把论文抓进每日 `content/`。
- 详见「每周学术雷达（阶段三）」一节。

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
date: 2026-08-05
title: 标题
source: 来源名（可选）
source_url: https://（可选）
tags: 9bar, 水温, 萃取率tds, 意式基础   # 2-5 个具体主题标签，逗号分隔
score: 85                             # 0-100 质量分（管线落盘；手写可选）
kind: deepdive                        # 内容处理方式：as-is/translate/summary/deepdive（管线落盘）
content_type: research               # 内容性质（管线落盘）：expert_experiment / independent_review / news / community_case / announcement / research
score_dims: relevance=28|novelty=16|evidence=13|actionability=12|params=10|timeliness=5  # 六维明细（管线落盘）
why_read: 一句话说明为什么值得读        # 「为什么值得读」短句（管线落盘，可选）
related: ["标题|https://...", "..."]   # 同题事件折叠的补充来源（48h 聚类产出；可选，不动 references）
---

正文用 Markdown。要点、原理、参考链接…
```

> **`content_type` 与 `kind` 是正交的两个维度**：`content_type` 描述「这条内容是什么」（实验/评测/消息/社区个案/公告/学术），决定证据维度打分与卡片上的类型标签；`kind` 描述「这条内容怎么处理」（原样/翻译/摘要/深度解读），决定正文生成方式。两者都保留、仅做映射对齐，不合并成一套。

> **`related` 与 `references` 不复用**：`references` 仅用于「深度解读」区块引用的权威源（语义不同）；同题折叠的补充来源走独立的 `related` 字段，两者不混。

标签是**动态**的：手写时自由给每条打 2-5 个具体标签（如 `9bar`/`水温`/`研磨度`/`咖啡机`/`新手`/`评测`）；
接入 LLM 后由模型自动生成，词表不固定。构建期会汇总全站标签词频，前端据此动态渲染筛选 chips 与标签页。

> **当前为观察期**：标签的**展示与生成已通过 `config.example.toml` 的 `[ui].show_tags = false` 暂时关闭**——
> 现有标签生成机制较粗糙、标签过多且无实际意义。待采集一段时间、明确标签的必要性后再评估机制，
> 改回 `true` 即可恢复；`content/*.md` 中的 `tags` 数据字段保留不动，不受影响。

## 分级内容处理（kind 分流）

管线对每条内容分**两段**处理（LLM 启用时，见 `src/score.py` 模块注释；此处的「段」指 LLM 内部评估流程，与项目「阶段一/二/三」优化分期无关）：

- **评估第一段（轻量评估，不注入知识库）**：LLM 一次性输出 `tags` / `summary`（处理后正文）/ `score` / `kind`。
- **评估第二段（仅 `kind=deepdive` 的内容）**：注入常青知识库生成「深度解读」区块，由 `[llm].deepdive_enabled` 总开关控制。

`kind` 四值决定了「正文」怎么来：

| kind | 适用情况 | 正文产出 |
|---|---|---|
| `as-is` | 中文精炼原文 | 原文直出，不做摘要/改写 |
| `translate` | 英文等非中文精炼原文 | 翻译成中文直出，不压缩不精炼 |
| `summary` | 原文冗长/信息密度低 | 精炼中文摘要 |
| `deepdive` | 原理性强/反常识/信息密度高 | 精炼中文摘要 + 「深度解读」区块 |

简单资讯（简讯/新品发布等）不会被强行深度解读；`score < min_score` 的内容照旧不收录。
单日页标题按当天实际含深度解读的篇数动态显示（无解读时不显示该文案）。

## 编辑判断管线（阶段二：初筛 → 六维评分 → 聚类）

管线对每条进入的内容做三级「编辑判断」，把 RSS 摘要墙压成 5–12 条高相关、可解释的「昨日精选」。所有逻辑在 `src/score.py`，落盘在 `src/pipeline.py`。

### 1. 初筛（prescreen，Two-Pass 第一段）

只看 **标题 + RSS 摘要 + 来源身份**，便宜地淘汰不值得后续成本的内容：

- **LLM 优先**：`_llm_prescreen` 输出 `{accept, content_type, espresso_core, reason}`，直接拒绝非意式核心、纯展示帖、求助/选购咨询、广告/软文、低相关研究。
- **规则回退**（无 LLM / LLM 失败）：只挡**明显**非意式或低质形态（纯展示、求助选购、广告、健康营养话题），其余一律放行到六维评分阶段，由 `min_score` 硬门槛决定去留。
  - 设计取舍：规则回退**不**自行做「是否意式核心」的硬判定——因为① 源级关键词预过滤（`_source_prefilter`）已把泛咖啡内容挡在门外；② 真正的灌水条（如「咖啡渣电脑包」「每天五杯咖啡」）即便放行，六维评分也会因 `relevance→0` / `evidence` 低跌破 60（已单测验证）；③ 若在初筛也卡核心词，无 LLM 时日报会直接空掉。
- 与 `fetch.py` 的 `_source_prefilter`（更前置、零成本的源级关键词闸门）**串联不冲突**。

### 2. 六维可解释评分

精评（Two-Pass 第二段）对每条内容打**六维明细**，而非单分黑箱；总分 = 六维之和（满分 100）：

| 维度 | 满分 | 说明 |
|---|---:|---|
| 意式相关性 relevance | 30 | 是否直接服务于意式萃取/器具/参数/工艺；按核心词命中密度阶梯给分，标题命中额外加权 |
| 新颖性 novelty | 20 | 是否提供新信息/新发现/反常识结论 |
| 可操作性 actionability | 20 | 读者能否据此改变自己的操作 |
| 证据质量 evidence | 15 | **来源身份唯一参与打分的地方**：同行评审/可复现实验 > 专家实验/独立实测 > 行业报道 > 社区个案 |
| 参数具体度 params | 10 | 是否给出具体数值（粉量/液重/时间/压力/温度/粒径/TDS） |
| 时效性 timeliness | 5 | 信息新鲜度与讨论热度 |

- **刻意不用「来源分数 × 系数」**：那种做法会让权威但无关的内容自动高分（例：Barista Hustle 发一篇滤泡文章也被抬到 80+）。来源只经 `evidence` 一维参与打分，另外只影响配额与同分排序。
- **分档**：85+ 罕见强证据 · 70–84 日报主内容 · 60–69 确有补充价值才收 · **<60 不发布**（`llm.min_score = 60` 硬门槛）。
- **同分排序**：证据等级 > 来源多样性 > 事件是否重复（不单看总分）。
- LLM 启用时基于**全文**精评（初筛通过后才抓全文，见下）；未启用时同样输出六维明细（规则启发式），字段一致。六维明细落 `score_dims` 到 frontmatter，`why_read` 一句「为什么值得读」同步落盘（卡片展示用）。

### 3. 按需全文抓取（稀缺资源）

RSS 摘要普遍被截断（几十到两百字），基于截断摘要做精评容易让模型「补全」出原文没有的参数与结论。全文能消除这类虚构，但抓取有流量与封禁成本，因此它是**稀缺资源**：

- 只对 **① 白名单来源**（config 里 `full_text = true`，如 Barista Hustle / Coffee Ad Astra / CoffeeGeek / Daily Coffee News / Whole Latte Love / Clive Coffee）**② 初筛 `accept` 的条目**——二者同时满足才抓（`fetch.py` 的 `fetch_full_article`）。
- 轻量正文提取（`extract_article_text`）不引重依赖：剥样板块 → 优先 `<article>/<main>` 容器 → 取 `<p>/<li>` 段落拼接；低于阈值回退 RSS 摘要。
- `[fetch]` 下的 `fulltext_enabled` / `fulltext_max_per_run` / `fulltext_delay` / `fulltext_timeout` 是成本闸门，防止一次运行烧太多流量或被封。
- 实测收益：Barista Hustle 概念文仅 RSS 摘要时六维约 51 分（不过线），抓全文后升至 80+ 正确收录——印证「先初筛、后全文」的价值。

### 4. 48h 轻量事件聚类

同一个新品发布 / 同一篇研究的媒体报道 / 同一个调参讨论，会在多家源或 48h 内被重复收录。聚类后只保留**评分最高**（同分则证据等级高者优先）的一条作主卡，其余折叠进主卡的 `related` 字段（补充来源），不再单独成卡：

- **不引向量库**：只用「显著签名词」做集合交并——意式核心词（排除最泛的 espresso/意式浓缩）、标题实体专名（如 Zerno Z1 / La Marzocco）、机型/型号代码（如 Micra / DE1 / Z1）。两条共享 ≥2 个显著签名词、或共享 ≥1 个实体/型号即判同题。
- 规模尚小，关键词聚类零外部依赖、可复现、结果可解释；不够再加 SQLite + embedding。
- `related` 刻意复用 `references` 的 `标题|url` 格式但**独立字段**，不打乱深度解读的参考来源机制。

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

## 运行质量报告（reports/）

每次管线运行结束，`src/quality_report.py` 在 `reports/` 落两份产物（gitignore，不提交）：

- `quality_<date>.json`：机器可读，供趋势统计 / CI 断言；
- `quality_<date>.md`：人类可读摘要，贴 Issue / 周报用。

核心指标（对应阶段二验收）：

- **每源**：候选数 / 入选数 / 拒绝数 / 平均分 / 拒绝原因分布；
- **全局**：来源占比（入选）、重复率（去重跳过 + 事件聚类折叠）、意式核心占比、85+ 强证据条数、深度解读条数；
- **合并抓取失败维度**（复用阶段一的 `fetch_failures_<date>.json`）：每源失败率、限流/封禁标记。

用途：观察 ≥14 期后据真实占比与拒绝原因调参（配额、源过滤、评分阈值），也为「同题是否重复」「灌水是否过线」提供客观证据。

## 基础 / 常青知识库（深度解读的来源）

网站只展示「每日资讯流」（`content/`）。另有 **`knowledge/`** 作为**私有**的权威知识库：

- **定位**：每个主题一篇，是对**多篇权威文章的综合**（而非搬运单篇），正文末尾用「`## 参考来源`」列出该主题涉及的**全部源头**。主题不限——凡能为 LLM 解读资讯提供底层依据的内容都可入库（含科研综述），当前按五类组织（2026-08 扩充后约 23 篇）：
  - **萃取科学**：`9bar`、`预浸泡`、`通道效应`、`萃取率tds`、`压力曲线`、`crema`、`turbo-shot` 等；
  - **设备器具**：`研磨度`、`刀盘几何`、`粉碗`、`锅炉与温度稳定性`、`磨豆机工作流` 等；
  - **豆与水**：`水质`、`烘焙与养豆`、`豆种与处理法` 等；
  - **感官方法论**：`粉水比`、`布粉wdt`、`填压`、`水温`、`感官诊断`、`奶泡`、`测量与调参` 等；
  - **科研综述**：`渗流物理与萃取建模`（由周级学术雷达补丁持续追加）。
- **不直接上站**：`build.py` 只加载 `content/`，完全不碰 `knowledge/`，因此常青库天然不出现在公开站点上。
- **怎么用**：管线只对 `kind=deepdive` 的新闻（阶段二）把整库（或小库默认的「全量注入」，见 `config.example.toml` 的 `[knowledge]`）作为背景上下文注入 LLM，并要求 AI **不要简单复述新闻**，而是结合背景从原理/操作/器具/对比/误区等角度做**多角度深度整理**，且在引用某个知识点时**注明其权威来源**。生成的内容里会带一个独立的「深度解读」区块。
- **维护**：`python scripts/new_knowledge.py "9 bar 水压"` 生成主题模板；人工补充/校订综合内容与来源即可。当前库约 23 篇 / 18K 字符，`max_chars = 24000`；保持 `mode = "all"` 最全面，当库总量达到预算约 80% 或注入成本明显上升时，评估切 `mode = "recall"`（按标签/概念高召回）以控 token。
- **无 LLM 时**：走规则回退，正文取抓取摘要/标题，不产出「深度解读」区块（翻译与深度解读均依赖 LLM）。

## 每周学术雷达（阶段三）

独立的**周级管线**，把同行评审研究沉淀为「研究卡 + 知识库补丁」，与每日 RSS 流**解耦**——不进 `content/`、不污染每日站点流。

### 触发与编排

- **CI**：`.github/workflows/weekly.yml` 在**每周一 17:10 UTC**（周二 01:10 北京，错峰每日管线 16:40 UTC）运行，也可 `workflow_dispatch` 手动触发。步骈：装依赖 → `python -m src.academic`（可加 `--date YYYY-MM-DD` 覆盖日期）→ 把本周 `research/` 变化提交推送。
- **本地**：`python -m src.academic` 跑周报；`python -m src.academic apply <patch.json>` 应用一条知识库补丁提案。
- **检索源**：`config.example.toml` 的 `[[sources]]` 里 `type = "academic"`（默认 `enabled = false`，专为周级 CI 服务，确保每日管线不会把它抓进 `content/`）。

### 抓取与消歧（`fetch_academic`）

OpenAlex（`abstract.search` 严格 AND：`espresso` ∩ `extraction`）+ Crossref（DOI/期刊补全）双源：

- **严格 AND**：多个 `academic_must` 词全部命中才保留；`academic_exclude` 标题/摘要命中任一即丢弃（tea / cold brew / sensory / consumer 等）。
- **咖啡领域消歧**：缩写歧义会污染结果（如 `ESPReSSO` 是单点登录协议、`cembalo` 是乐器），故要求标题或摘要至少命中一个咖啡领域词（coffee/bean/roast/brew/crema/grinder/portafilter…），否则排除；另加强非咖啡排除词（single sign-on / sso / login / authentication 等）。OpenAlex 已内置 AND，本地不再重检；Crossref 宽松检索才强制 `must` 重检。
- 跨源按 DOI（空则标题）去重；`academic_filters` 透传 OpenAlex filter（如 `from_publication_date:2015-01-01`）。

### 研究卡固定字段

每条论文产出一张研究卡（`research/<date>-<slug>.md`），LLM 优先抽取、无 LLM 规则回退占位，固定字段：

`研究对象 subject` / `实验条件 conditions` / `核心发现 finding` / `实际影响 implication` / `不能推出 not_claim` / `证据等级 evidence_level` / `DOI`。

### 知识库补丁机制

- 每张研究卡同时产出一份补丁提案 `knowledge/patches/<date>-<slug>.json`（含建议并入的主题 `kb_topic`）。**未应用前不入库**（`knowledge/patches/` gitignore）。
- 应用：`python -m src.academic apply <patch.json>` → 若 `knowledge/<topic>.md` 已存在则追加「`## 补充（日期）`」段；否则新建综合条目。
- **主题映射**：补丁的 `kb_topic` 经 `KB_TOPIC_TO_SLUG` 解析到既有主题（如「萃取」→ `extraction-rate-tds`、`研磨` → `grind`），避免主题碎片化落到平行新建文件。
- 事件触发、不强求日更：真正改变知识判断的论文与 Coffee Ad Astra 内容才补入。

### 周报与人工抽检

- `research/weekly-<date>.md` + `research/latest.md`：本周研究卡索引（标题 / 证据等级 / 研究对象），由周级 CI 提交到仓库供人工复核。
- `reports/research_spotcheck_<date>.md`：从本周研究卡抽 **10 条**的人工抽检清单（标题 / 证据等级 / 核心发现 / 入库？勾选），积累判断标准（暂不训练模型）。`reports/` 是运行时产物，gitignore。
- **观察 ≥14 期后**：再决定是否启用更严格的深度解读触发规则。

## 范围与边界（暂不做 / 后续候选）

> 以下为项目早期「优化任务清单」沉淀的范围护栏，固化于此以免边界漂移。

**明确排除（避免过度工程）**

- 实时层 / 多层调度：保持每日一次 Actions + 一次构建 + 静态站的架构。
- 自托管 RSSHub；Home-Barista 硬绕访问限制（等稳定合规入口）。
- 向量数据库（FAISS/Milvus）、LightGBM 训练、200–500 条标注。
- 社区图片批量多模态分析（未来只考虑曲线/仪表/拆机图）。
- 标签 UI 重开；YAML 替换 TOML（无实际收益）。
- 中文源（知乎/B站）自动接入（先人工/半自动精选，第二阶段再说）。

**后续候选（观察后再定）**

- Home-Barista 技术社区源（需稳定合规入口）。
- 品牌官方 `official_watchlist` 低频监测：La Marzocco、Decent、Lelit、Profitec/ECM、Breville/Sage、Gaggia、Flair、Cafelat、Eureka、Mazzer、Mahlkönig、Niche、Zerno、Timemore、1Zpresso、Option-O（只监测新品/规格/固件/召回）。
- SCA / Coffee Science Foundation（周度或事件触发）。
- 读者反馈按钮、视觉分析（数据量足够后）。
