# 知识库维护手册（AI 执行指引）

> 本文件是 `knowledge/` 常青知识库的**长期运营方法论**。AI 在执行任何知识库相关任务
> （新增/更新/拆分/合并条目、apply 学术补丁、周/月巡检）前，应先读本文件。
> 注意：本文件**没有 frontmatter**——`load_knowledge()` 只认带 `topic` 的文件，
> 无 frontmatter 的文件会被自动跳过，**切勿给本文件加 frontmatter**。

核心心法：**让管线自己告诉你缺什么（信号驱动），让学术雷达自动喂科研内容（自动化），
人只做来源核查这一件机器做不好的事（质量控制）。宁缺毋滥——注水条目会稀释注入
上下文质量，反而降低 deepdive 水平。**

---

## 1. 收集渠道：广撒网（收集要宽，筛选靠第 2/3 节把关）

> **元规则：下面的名单是「种子」而非「白名单」。** 任何来源只要能通过第 3 节的
> 可靠性评判即可使用，**不要因为某来源不在名单里就拒绝它**。执行时应主动探索
> 名单之外的来源；发现可靠新来源时随手补进本表（月度维护动作之一）。
> 收集阶段的默认姿态是「先记下来」，是否入库由第 2 节三问和第 3 节分级决定。

### 1.0 管线副产品（缺口信号的第一来源，每周）
grep 近期 deepdive 正文中的库外概念；看 quality_report 的 deepdive 条数与
references；看学术补丁「新建 vs 追加」比例（新建多 = 映射/覆盖有缺口）。

### 1.1 学术 / 科研
- 已自动化：OpenAlex + Crossref（周级雷达产出研究卡 + 补丁，审核后 apply）。
- 主动可查：Google Scholar 关键词订阅；ASIC 会议论文集；UC Davis Coffee Center；
  Coffee Science 期刊（巴西 UFLA）；World Coffee Research（感官词典、品种研究）；
  SCA 研究报告。

### 1.2 独立实验 / 深度技术博客
Barista Hustle（含播客）、Coffee Ad Astra（Jonathan Gagné）、Socratic Coffee、
Scott Rao、KRUVE（粒径/筛分研究）、Weber Workshops 技术白皮书等。

### 1.3 视频 / 播客创作者
- YouTube：James Hoffmann、Lance Hedrick、Brian Quan（设备向）、Sprometheus、
  European Coffee Trip、Sweet Maria's、Boot Coffee 等。
- 播客：Filter Stories（咖啡科学叙事）、Making Coffee（Lucia Solis，处理法/发酵）、
  Keys to the Shop（门店运营）等。

### 1.4 行业媒体
Sprudge、Perfect Daily Grind、Daily Coffee News、Barista Magazine、Standart、
Roast Magazine、Global Coffee Report、Comunicaffe 等。

### 1.5 社区（经验性说法的富矿，引用时标注确定性）
r/espresso、r/Coffee、Home-Barista、CoffeeGeek、Decent Diaspora、
Espresso Aficionados（Discord）、Kaffee-Netz（德语社区）等。

### 1.6 中文渠道
B站/小红书/知乎的咖啡创作者与话题（如牛小咖等）、微信公众号（咖啡沙龙、
Torch 炬点、治光师等）、什么值得买、豆瓣小组等。
中文源以「发现线索」为主，关键结论尽量回溯到更高分级的来源交叉验证。

### 1.7 厂商技术资料（取工程事实，弃营销话术）
La Marzocco、Decent Espresso（博客+论坛技术浓度高）、Weber Workshops、Baratza、
Fellow、Acaia、Niche 等的官方文档 / 白皮书。

### 1.8 标准组织与比赛
SCA（标准体系、25 Magazine）、WBC 等赛事 routine（技术创新的先行指标，
如新处理法、冷冻研磨往往先出现在赛场）、CQI（Q 体系）。

### 1.9 书籍（长青底层，新条目的骨架来源）
Illy & Viani《Espresso Coffee: The Science of Quality》、Rao《The Professional
Barista's Handbook》、Hoffmann《The World Atlas of Coffee》、Hendon &
Colonna-Dashwood《Water for Coffee》、Gagné《The Physics of Filter Coffee》、
Hoos《Modulating the Flavor Profile of Coffee》等。

## 2. 筛选：入库三问

全过才写，任一不过则进候选池（见第 7 节）：

1. **常青吗？** 底层原理/方法论，两年后仍有参考价值。资讯、新品、行情一律不入。
2. **为解读服务吗？** 能帮助 LLM 理解未来会出现的新闻吗？（知识库是解读依据，不是百科。）
3. **可综合吗？** 能找到 ≥2 个**独立**权威来源？找不到就挂候选池，不硬写。

排除：时效性内容、单一产品信息、纯操作步骤教程、只有单一来源的主张。

优先级排序信号：内容高频标签 > deepdive 实际触发主题 > 社区高频问题 > 个人兴趣。

## 3. 可靠性评判

### 来源分级（高 → 低）
1. 同行评审论文（**用 DOI 链接**，最稳）
2. 有实验数据的独立研究（Socratic Coffee、Coffee Ad Astra）
3. 公认专家综合（Barista Hustle、Scott Rao、Hoffmann）
4. 厂商资料（La Marzocco 等——注意立场，只取工程事实部分）
5. 社区经验共识（必须标注为经验性说法）

### 确定性四档（写作时必须分档表述，这是防幻觉的关键）
- 「共识」：多源一致（如「低压预浸泡减少通道」）
- 「实验证据」：有数据支撑，引具体实验（如 Socratic 的 RDT 对照）
- 「X 认为」：单一权威主张，署名呈现
- 「争议点」：写进「不同权威的侧重」子列表，呈现分歧、**不裁决**

### 数字核查规则
凡出现参数区间（90-96°C、1:2 粉液比），必须能在来源里找到出处；找不到就删掉数字。
博客源沿用**根页引用**惯例（BH / Ad Astra 有 Cloudflare 拦截，具体文章 URL 无法
逐篇验证时宁用根页，**不编造深链**）。

## 4. 归类与生命周期

- **一篇一主题，slug 稳定**。新建前必查两处：① `knowledge/` 现有条目（防重复）；
  ② `src/academic.py` 的 `KB_TOPIC_TO_SLUG`（新主题要同步加映射，让学术补丁能落进来）。
- **映射规则陷阱**：`KB_TOPIC_TO_SLUG` 按插入顺序做子串匹配、命中即停——
  **更具体的 key 必须前置**（如「压力曲线」在「压力」前、「奶泡」在「温度」前、
  「平刀/锥刀」在「粒径」前）。
- **结构靠 tags/concepts 关联网，不靠目录**：新条目的 tags/concepts 至少与 2 篇
  既有条目有交集，全量注入时 LLM 能自己串起知识网络。
- 生命周期判据：
  - **追加**：学术补丁以「## 补充（日期）」段落入既有条目
  - **拆分**：单篇 >1100 字符且持续被 deepdive 引用 → 拆子主题 + 同步加映射
  - **合并**：两篇 8 周+ 未被引用且 concepts 重叠 → 合并
  - **退休**：长期未被引用且概念已被覆盖 → 删除或并入

## 5. 写作规范速查（与现有条目对齐，样板见 `9bar.md`）

1. 篇幅 700-900 字符（Python len 口径，含 frontmatter）。
2. frontmatter 恰好四字段：`topic` / `title` / `tags`（2-4 个，优先复用标签词表）/
   `concepts`（4-6 个），逗号+空格分隔。
3. 导语固定句式：「对「X」的综合梳理（跨多篇权威）：」单独一行。
4. 正文 3-5 个加粗要点；必含「**不同权威的侧重**：」嵌套子列表（2-3 个子项各注权威名）；
   末项为「实践意义/现代变量」类收束。
5. 末尾「## 参考来源」2-4 条 Markdown 链接，全部真实可解析。
6. 语气：综合、陈述、中文；给数字区间；不搬运单篇、不写教程步骤。
7. 用脚手架生成模板再填充：`python scripts/new_knowledge.py "<topic>" --slug <slug>`。

## 6. 节奏与巡检清单

### 每周（约 15 分钟，建议周一配合学术雷达）
```bash
# 1. 学术补丁：审核后 apply（新建比例高 → 查 KB_TOPIC_TO_SLUG 缺映射）
python -m src.academic apply <patch.json>
# 2. deepdive 触发情况
grep -h "深度解读" reports/quality_*.json | tail -7
# 3. references 抽检 2-3 条：URL 是否幻觉、是否真来自知识库「## 参考来源」
grep -A5 "^references:" content/*.md | tail -20
# 4. 库外概念缺口：近期 deepdive 正文里出现的、知识库没有的概念
```
产出：候选池更新 + 补丁入库。

### 每月（约 1 小时）
- 缺口评审：候选池中凑够 ≥2 独立来源的主题，写 1-3 篇（单篇成本 ≤30 分钟：
  脚手架 → AI 起草 → **人工只做来源真实性与数字出处核查**）。
- 巡检权威源（第 1.2-1.9 节，轮着看，不必每月全覆盖）。
- **渠道名单维护**：本月实际用到的新来源补进第 1 节对应分类；失效来源标记或移除。
- 每次入库一个 commit，git log 即库的 changelog。

### 每季
```bash
wc -c knowledge/*.md   # 总量 vs max_chars=24000：≥80%（约19K）启动 recall 评估
```
- 死条目清理（按第 4 节判据）；映射表查漏。
- **切 recall 判据**（满足任一）：① 库总量 ≥ 预算 80%；② 单次注入字符 >20K
  致成本/延迟明显上升；③ deepdive 引用主题占比持续低于 30%。

## 7. 候选池

> 主题 + 缺口信号 + 已找到的 1 个来源；凑够 2 个独立来源再动笔。

| 主题 | 缺口信号 | 已有来源 | 状态 |
|---|---|---|---|
| 蒸汽锅炉压力与奶泡动力（steam-boiler-pressure） | 备选第 15 篇 | — | 待观察标签分布 |
| 布粉工具实证比较（布粉针/布粉器/压粉锤） | 备选第 16 篇 | — | 待观察标签分布 |

---

*配套文档：总览见项目 `README.md`「基础 / 常青知识库」一节；来源清单见 `SOURCES.md`；
注入逻辑见 `src/knowledge.py` docstring。本手册与上述文档有冲突时以代码行为准。*
