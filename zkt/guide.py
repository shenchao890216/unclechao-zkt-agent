"""guide.py —— zkt guide:使用手册页。自包含 HTML,实时状态注入,同星图视觉。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from card import load_all

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "guide.html"


def collect_stats() -> dict:
    """手册顶部的实时状态条。"""
    cards = load_all()
    drafts = [c for c in cards if c.path and c.path.parent.name == "inbox"]
    links = sum(len(c.links) for c in cards)
    return {
        "total": len(cards),
        "pending": len(drafts),
        "links": links,
        "auto": sum(1 for c in cards if c.auto),
    }


GUIDE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>卡片盒 · 使用指南</title>
<style>
  :root {
    --bg: #0d1117; --panel: rgba(22, 27, 34, .6);
    --border: rgba(240, 246, 252, .12);
    --text: #e6edf3; --dim: #8b949e;
    --accent: #58a6ff; --orange: #f0883e; --green: #3fb950; --purple: #bc8cff;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, "PingFang SC", sans-serif;
    font-size: 14.5px; line-height: 1.85;
  }
  .wrap { max-width: 780px; margin: 0 auto; padding: 48px 28px 80px; }

  header h1 { font-size: 26px; margin: 0 0 6px; font-weight: 700; }
  header .sub { color: var(--dim); font-size: 14px; }
  .stats {
    display: flex; gap: 12px; margin: 22px 0 8px; flex-wrap: wrap;
  }
  .stat {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 10px 18px; text-align: center;
    backdrop-filter: blur(8px); min-width: 92px;
  }
  .stat b { display: block; font-size: 22px; font-weight: 600; }
  .stat span { color: var(--dim); font-size: 12px; }
  .stat.pulse { border-color: var(--orange); }
  .stat.pulse b { color: var(--orange); }

  nav {
    position: sticky; top: 0; z-index: 10; display: flex; gap: 4px;
    background: rgba(13, 17, 23, .92); backdrop-filter: blur(10px);
    padding: 10px 0; margin: 18px 0 8px; border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }
  nav a {
    color: var(--dim); text-decoration: none; font-size: 13px;
    padding: 4px 12px; border-radius: 14px;
  }
  nav a:hover { color: var(--text); background: rgba(240, 246, 252, .08); }

  section { margin-top: 44px; }
  h2 {
    font-size: 19px; margin: 0 0 14px; font-weight: 600;
    padding-bottom: 8px; border-bottom: 1px solid var(--border);
  }
  h2 .no { color: var(--accent); margin-right: 8px; font-family: monospace; }

  .concept {
    display: flex; gap: 14px; margin: 14px 0; align-items: flex-start;
  }
  .concept .icon { font-size: 22px; line-height: 1.4; }
  .concept b { color: var(--text); }
  .concept .desc { color: var(--dim); font-size: 13.5px; }
  .concept code { color: var(--green); }

  .flow {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px 24px; margin: 14px 0;
    font-family: ui-monospace, monospace; font-size: 13px;
    line-height: 1.9; color: var(--dim); white-space: pre;
    overflow-x: auto;
  }
  .flow b { color: var(--text); font-weight: 500; }
  .flow .hl { color: var(--orange); }
  .flow .hl2 { color: var(--purple); }

  table { width: 100%; border-collapse: collapse; margin: 14px 0; }
  th {
    text-align: left; color: var(--dim); font-size: 12px;
    font-weight: 500; padding: 8px 10px; border-bottom: 1px solid var(--border);
    letter-spacing: 1px;
  }
  td { padding: 9px 10px; border-bottom: 1px solid rgba(240,246,252,.06);
       vertical-align: top; }
  td.scene { color: var(--dim); font-size: 13px; white-space: nowrap; }
  .cmd {
    font-family: ui-monospace, monospace; font-size: 12.5px;
    color: var(--green); cursor: pointer; position: relative;
    background: rgba(63, 185, 80, .08); padding: 2px 8px;
    border-radius: 6px; display: inline-block; margin: 2px 0;
    border: 1px solid rgba(63, 185, 80, .2);
  }
  .cmd:hover { background: rgba(63, 185, 80, .16); }
  .cmd .tip {
    position: absolute; top: -26px; left: 50%; transform: translateX(-50%);
    background: #238636; color: #fff; font-size: 11px; padding: 2px 8px;
    border-radius: 4px; opacity: 0; transition: opacity .2s;
    pointer-events: none; white-space: nowrap;
  }
  .cmd.copied .tip { opacity: 1; }
  .cmd-note { color: var(--dim); font-size: 12.5px; }

  .guard {
    display: flex; gap: 14px; margin: 16px 0; padding: 14px 16px;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px;
  }
  .guard .mark { color: var(--orange); font-size: 18px; }
  .guard b { display: block; margin-bottom: 4px; }
  .guard p { margin: 0; color: var(--dim); font-size: 13.5px; }

  .moment {
    border-left: 3px solid var(--accent); padding: 4px 0 4px 14px;
    margin: 16px 0;
  }
  .moment b { display: block; }
  .moment .a { color: var(--dim); font-size: 13.5px; margin-top: 4px; }
  .moment .a::before { content: "→ "; color: var(--green); }

  footer { margin-top: 60px; color: var(--dim); font-size: 12px;
           border-top: 1px solid var(--border); padding-top: 16px; }
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>卡片盒 · 使用指南</h1>
  <div class="sub">消化输入 → 原子卡片 → 链接成簇 → 簇长文章</div>
  <div class="stats" id="stats"></div>
</header>

<nav>
  <a href="#what">这是什么</a>
  <a href="#concepts">核心概念</a>
  <a href="#loop">日常循环</a>
  <a href="#commands">命令速查</a>
  <a href="#guards">三条护栏</a>
  <a href="#moments">常见时刻</a>
</nav>

<section id="what">
  <h2><span class="no">01</span>这是什么</h2>
  <p>一个跑在你终端里的卢曼卡片盒(Zettelkasten)助手。你把读到的文章、冒出来的想法喂给它,它消化成<b>原子卡片</b>存进草稿区,并主动在盒里找相关旧卡、建立<b>带理由的链接</b>;卡片攒够密度,它帮你从卡片簇长出文章大纲、装配成草稿。</p>
  <p style="color:var(--dim)">它只负责建议和草稿。<b>转正和删除永远是你的签字权</b>——这是设计,不是缺陷。</p>
</section>

<section id="concepts">
  <h2><span class="no">02</span>核心概念</h2>
  <div class="concept"><div class="icon">📦</div><div>
    <b>卡片盒(zk/)</b>
    <div class="desc">一个装 markdown 卡片的文件夹。每张卡 = 一个观点,frontmatter 记元数据(id/链接/auto 标记),正文用自己的话写。</div>
  </div></div>
  <div class="concept"><div class="icon">🟠</div><div>
    <b>草稿区(inbox/)</b>
    <div class="desc">agent 消化的卡先进这里,带 <code>auto</code> 标记。是待审稿,不是正式内容。</div>
  </div></div>
  <div class="concept"><div class="icon">🟢</div><div>
    <b>转正区(cards/)</b>
    <div class="desc">你审过、签过字的卡住这里。只有转正的卡才算"我的知识"。</div>
  </div></div>
  <div class="concept"><div class="icon">🕸️</div><div>
    <b>簇(cluster)</b>
    <div class="desc">互链的卡片自然抱成的团。簇到一定规模(3 张以上)说明话题密度够了,可以考虑收割成文章。</div>
  </div></div>
</section>

<section id="loop">
  <h2><span class="no">03</span>日常循环</h2>
  <div class="flow">读到值得记的东西
  │
  ▼
<span class="hl">zkt ingest "链接或想法"</span>     ← 喂料(每天,30秒)
  │        agent 消化 → 原子卡落草稿区 → 找旧卡建链
  ▼
<span class="hl">zkt inbox --all</span>            ← 审卡(周末,15分钟)
  │        逐张过目:y 转正 / n 跳过 / q 退出
  ▼
<span class="hl">zkt clusters</span>               ← 看哪块熟了
  │
  ▼
<span class="hl2">zkt outline</span> → 改大纲 → <span class="hl2">zkt write</span>   ← 收割(攒够一簇)
  │                                手改草稿 → 发布
  ▼
<span class="hl2">zkt graph</span>                   ← 随时看星图全貌</div>
</section>

<section id="commands">
  <h2><span class="no">04</span>命令速查<span style="font-size:12px;color:var(--dim);font-weight:400"> · 点击命令复制</span></h2>
  <table>
    <tr><th>场景</th><th>命令</th><th>说明</th></tr>
    <tr><td class="scene" rowspan="2">喂料</td>
        <td><span class="cmd" data-cmd='zkt ingest "https://…"'>zkt ingest "url"<span class="tip">已复制</span></span></td>
        <td>消化文章(约 1 分钟,含建链)</td></tr>
    <tr><td><span class="cmd" data-cmd='zkt ingest "想法内容"'>zkt ingest "想法"<span class="tip">已复制</span></span></td>
        <td>直接记录一个想法</td></tr>
    <tr><td class="scene" rowspan="3">审卡</td>
        <td><span class="cmd" data-cmd="zkt inbox">zkt inbox<span class="tip">已复制</span></span></td>
        <td>列出待审卡</td></tr>
    <tr><td><span class="cmd" data-cmd="zkt inbox --all">zkt inbox --all<span class="tip">已复制</span></span></td>
        <td>逐张过目,y/n/q</td></tr>
    <tr><td><span class="cmd" data-cmd="zkt promote 卡片id">zkt promote id<span class="tip">已复制</span></span></td>
        <td>转正一张卡</td></tr>
    <tr><td class="scene" rowspan="2">签字</td>
        <td><span class="cmd" data-cmd="zkt delete 卡片id --confirm">zkt delete id --confirm<span class="tip">已复制</span></span></td>
        <td>删卡(先看反链报告)</td></tr>
    <tr><td><span class="cmd" data-cmd="zkt new 标题">zkt new "标题"<span class="tip">已复制</span></span></td>
        <td>手写一张卡</td></tr>
    <tr><td class="scene" rowspan="3">收割</td>
        <td><span class="cmd" data-cmd="zkt clusters">zkt clusters<span class="tip">已复制</span></span></td>
        <td>看卡片簇</td></tr>
    <tr><td><span class="cmd" data-cmd="zkt outline">zkt outline<span class="tip">已复制</span></span></td>
        <td>最大簇 → 文章大纲</td></tr>
    <tr><td><span class="cmd" data-cmd="zkt write">zkt write<span class="tip">已复制</span></span></td>
        <td>大纲 → 装配草稿</td></tr>
    <tr><td class="scene" rowspan="3">观察</td>
        <td><span class="cmd" data-cmd="zkt graph">zkt graph<span class="tip">已复制</span></span></td>
        <td>星图可视化</td></tr>
    <tr><td><span class="cmd" data-cmd="zkt check">zkt check<span class="tip">已复制</span></span></td>
        <td>全盒体检</td></tr>
    <tr><td><span class="cmd" data-cmd="zkt audit">zkt audit<span class="tip">已复制</span></span></td>
        <td>审计日志(谁干了什么)</td></tr>
  </table>
</section>

<section id="guards">
  <h2><span class="no">05</span>三条护栏</h2>
  <p style="color:var(--dim)">自主权分配是这个 agent 的核心设计:建议权给模型,签字权留给你。</p>
  <div class="guard"><div class="mark">✍️</div><div>
    <b>转正必须你签字</b>
    <p>agent 存的卡只进草稿区,promote 只存在于 CLI。审卡时你审的是原子性——一张卡是不是真只有一个观点、是不是你自己的话。</p>
  </div></div>
  <div class="guard"><div class="mark">🗑️</div><div>
    <b>删除有双保险</b>
    <p>删前出反链报告(谁链到它、删了断几条),再要 --confirm 确认。拒绝手滑。</p>
  </div></div>
  <div class="guard"><div class="mark">📔</div><div>
    <b>所有动作留痕</b>
    <p>agent 的每次建卡、建链、搜索,你的每次转正、删除,全部记进 audit.jsonl。黑匣子永远可查。</p>
  </div></div>
</section>

<section id="moments">
  <h2><span class="no">06</span>常见时刻</h2>
  <div class="moment">
    <b>某篇文章 ingest 抓不到内容</b>
    <div class="a">页面是 JS 渲染的,抓回来是空壳。手动复制正文,用 <span class="cmd" data-cmd='zkt ingest "粘贴的正文"'>zkt ingest "正文"<span class="tip">已复制</span></span> 喂进去。</div>
  </div>
  <div class="moment">
    <b>觉得 agent 拆卡拆得不好</b>
    <div class="a">审核时 n 跳过,自己 <span class="cmd" data-cmd='zkt new "标题"'>zkt new<span class="tip">已复制</span></span> 手写一张。你的手写卡是盒子的质量校准器。</div>
  </div>
  <div class="moment">
    <b>搜不到明明记过的卡</b>
    <div class="a">已知短板:搜索是子串匹配,中文分词缺失。多换几个关键词;疼到第三次就该升级搜索了。</div>
  </div>
</section>

<footer>
  unclechao-agent · 卡片盒 agent v1 · Python + DeepSeek · 每次使用本页数据实时刷新,重新 <span style="color:var(--green)">zkt guide</span> 生成
</footer>

</div>

<script>
// 实时状态条
const STATS = __STATS__;
const statsEl = document.getElementById("stats");
const items = [
  {n: STATS.total, label: "张卡", cls: ""},
  {n: STATS.pending, label: "待审", cls: STATS.pending > 0 ? "pulse" : ""},
  {n: STATS.links, label: "条链接", cls: ""},
  {n: STATS.auto, label: "agent 存", cls: ""},
];
statsEl.innerHTML = items.map(i =>
  `<div class="stat ${i.cls}"><b>${i.n}</b><span>${i.label}</span></div>`).join("");
if (STATS.pending > 0) {
  statsEl.insertAdjacentHTML("afterend",
    `<p style="color:var(--orange);font-size:13px;margin-top:2px">` +
    `有 ${STATS.pending} 张待审卡,试试 <span class="cmd" data-cmd="zkt inbox --all">zkt inbox --all<span class="tip">已复制</span></span></p>`);
}

// 点击复制(clipboard 失败时降级为选中提示)
document.querySelectorAll(".cmd").forEach(el => {
  el.addEventListener("click", () => {
    const markCopied = () => {
      el.classList.add("copied");
      setTimeout(() => el.classList.remove("copied"), 1200);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(el.dataset.cmd)
        .then(markCopied)
        .catch(() => fallbackCopy(el, markCopied));
    } else {
      fallbackCopy(el, markCopied);
    }
  });
});

function fallbackCopy(el, done) {
  // 老浏览器/无剪贴板权限:划选文本,提示手动 Cmd+C
  const range = document.createRange();
  range.selectNodeContents(el);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  const tip = el.querySelector(".tip");
  if (tip) { tip.textContent = "已选中,Cmd+C"; }
  done();
}
</script>
</body>
</html>
"""


def build_html() -> Path:
    stats = json.dumps(collect_stats(), ensure_ascii=False)
    html = GUIDE_TEMPLATE.replace("__STATS__", stats)
    OUTPUT.write_text(html, encoding="utf-8")
    return OUTPUT


def cmd_guide(argv: list[str]) -> int:
    """zkt guide —— 打开使用手册网页(含盒子实时状态)。"""
    path = build_html()
    print(f"已生成: {path}")
    subprocess.run(["open", str(path)])  # macOS
    return 0
