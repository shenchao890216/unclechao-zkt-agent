# zkt —— 卢曼卡片盒对话式 Agent

一个跑在终端里的卢曼卡片盒(Zettelkasten)agent:全屏 TUI,自然语言操作,
AI 消化你的输入成原子卡片草稿——但**转正和删除的签字权永远在你手里**。

## 设计原则

- **签字权在人**:AI 只能建草稿、建链接、提议;转正/删除必须弹窗按 `y`,审计日志里 actor 记为 human
- **审计黑匣子**:每次操作(谁、何时、干了什么)追加写入 `audit.jsonl`,永远可查
- **原子卡片纪律**:一卡一观点、陈述句标题、链接必带理由,违宪拒收
- **换模型自由**:默认 DeepSeek,任何 OpenAI 兼容接口设三个环境变量即可切换

## 安装

```bash
pip install .                       # 克隆后本地安装
# 或
pip install git+https://github.com/shenchao890216/unclechao-zkt-agent
```

## 配置

```bash
cp .env.example .env
# 编辑 .env,填入你的 DEEPSEEK_API_KEY
```

换其他 OpenAI 兼容服务商:

```bash
export ZKT_BASE_URL="https://你的服务商"
export ZKT_API_KEY="你的key"
export ZKT_MODEL="模型名"
```

## 使用

```bash
zkt          # 进入全屏对话界面
```

```
你: 帮我消化这篇文章 https://...
⚙ create_card(...)        ← 工具调用可见
zkt: 已存 3 张草稿…        ← Markdown 实时渲染

你: 审卡
✋ 请求签字:转正           ← 弹窗,按 y 才生效
```

常用命令(输入 `/` 有自动补全):`/inbox` 审卡 · `/graph` 星图 · `/check` 体检 · `/clusters` 看簇 · `/audit` 审计日志

## 数据在哪

先选好盒子目录(写入 `~/.zktrc`,之后可随时 `zkt home <路径>` 换):

```bash
zkt home ~/my-zettelkasten
```

盒子结构:

```
<盒子>/
├── inbox/    草稿区:AI 写的卡都在这,等人审
├── cards/    正式卡:你签过字的
├── drafts/   文章草稿:攒够一簇卡后由 agent 起草
└── audit.jsonl  审计日志
```

## License

MIT
