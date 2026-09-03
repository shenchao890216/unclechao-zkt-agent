"""graph.py —— zkt graph:卡片盒可视化,生成自包含 HTML 力导向图。

设计:
- 只读:这是人的观察窗,不给 agent 注册任何工具。
- 自包含:vis-network 库和全部数据内嵌进单个 HTML,离线双击可用。
- 布局确定:坐标在 Python 里算好嵌入(固定随机种子 + 去重叠),
  前端关掉物理引擎——同数据刷新必得同一张图,节点互不重叠。
- 领域语义:节点形状/颜色编码 草稿/转正/人写/文章;悬停边看链接理由。
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from card import Card, load_all, zk_home

DRAFTS_DIR = zk_home() / "drafts"
VENDOR_JS = Path(__file__).resolve().parent / "vendor" / "vis-network.min.js"
OUTPUT = Path(__file__).resolve().parent.parent / "graph.html"


def collect_data() -> dict:
    """收集全部节点与边,输出给前端 JSON。"""
    cards = load_all()
    by_id = {c.id: c for c in cards}

    nodes = []
    for c in cards:
        in_inbox = c.path is not None and c.path.parent.name == "inbox"
        nodes.append({
            "id": c.id,
            "label": _short(c.title),
            "kind": "article" if False else ("human" if not c.auto else
                     ("draft" if in_inbox else "promoted")),
            # 详情面板用
            "title": c.title,
            "body": c.body,
            "source": c.source,
            "auto": c.auto,
            "status": "草稿(inbox)" if in_inbox else "已转正(cards)",
            "filename": c.path.name if c.path else "",
        })

    edges = []
    for c in cards:
        for link in c.links:
            if link.to in by_id:  # 死链宪法已拦,防御一下
                edges.append({
                    "from": c.id,
                    "to": link.to,
                    "why": link.why,
                    "kind": "link",
                })

    # 文章节点 + 装配边(outline.json 存在才有)
    if (DRAFTS_DIR / "outline.json").exists():
        outline = json.loads(
            (DRAFTS_DIR / "outline.json").read_text(encoding="utf-8")
        )
        draft_path = DRAFTS_DIR / f"{outline['title']}.md"
        nodes.append({
            "id": "article:" + outline["title"],
            "label": _short(outline["title"]),
            "kind": "article",
            "title": outline["title"],
            "thesis": outline["thesis"],
            "sections": [
                {"title": s["title"], "cards": s["cards"], "angle": s["angle"]}
                for s in outline["sections"]
            ],
            "draft": draft_path.read_text(encoding="utf-8")
                     if draft_path.exists() else "(草稿尚未生成)",
            "status": "文章(drafts)",
            "auto": True,
            "body": "",
            "source": "",
            "filename": draft_path.name if draft_path.exists() else "",
        })
        for i, sec in enumerate(outline["sections"], 1):
            for cid in sec["cards"]:
                if cid in by_id:
                    edges.append({
                        "from": "article:" + outline["title"],
                        "to": cid,
                        "why": f"第{i}节装配: {sec['title']}",
                        "kind": "assemble",
                    })

    # 布局在此算定,前端只渲染不模拟
    pos = compute_layout(nodes, edges)
    for n in nodes:
        x, y = pos[n["id"]]
        n["x"] = round(x, 1)
        n["y"] = round(y, 1)

    # 平行边错开:同一对端点(含方向)的多条边分配不同 roundness,
    # 前端画成不同弧度的曲线,避免完全重合
    _assign_roundness(edges)

    return {"nodes": nodes, "edges": edges}


def _assign_roundness(edges: list[dict]) -> None:
    """给同一对端点(含方向)的多条边分弧度。

    vis-network 的 roundness:0 = 直线,正值正向弧,负值反向弧。
    同组 n 条边:roundness 取 [-0.5, 0.5] 区间均分,保证弧度互不相撞。
    同对端点但方向相反的边(如 a->b 和 b->a)归不同组,因为连线对象不同。
    """
    from collections import defaultdict
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, e in enumerate(edges):
        groups[(e["from"], e["to"])].append(i)
    for key, idxs in groups.items():
        n = len(idxs)
        if n == 1:
            continue
        # n 条边在 [-0.6, 0.6] 区间均分,留出中间给直线组(若有)
        span = 1.2
        step = span / n if n > 1 else 0
        start = -span / 2 + step / 2
        for k, i in enumerate(idxs):
            edges[i]["roundness"] = round(start + step * k, 3)


def _short(title: str, limit: int = 14) -> str:
    return title if len(title) <= limit else title[:limit] + "…"


# ---------------------------------------------------------------------------
# 确定性布局:固定随机种子的力导向 + 去重叠。
# 在 Python 里算好坐标嵌入 HTML,前端不跑物理,刷新必得同一张图。
# ---------------------------------------------------------------------------

SEED = 42  # 固定种子:同数据 → 同布局,这是"每次刷新一个样"的根


def _segments_cross(p1, p2, p3, p4) -> bool:
    """两线段是否真正相交(不含共端点)。CCW 跨立实验。"""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)
    return (((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)))


def compute_layout(nodes: list[dict], edges: list[dict]) -> dict[str, tuple[float, float]]:
    """返回 {节点id: (x, y)}。确定性:种子固定、迭代次数固定。

    三阶段:
    1. 力导向:连线当弹簧,所有点对互斥,边交叉时端点互相轻推躲开。
       第三种力让布局自己长成交叉最少的形态,而不是事后硬推。
    2. 去重叠:任何两点距离小于安全间距时硬性推开。力导向不保证
       这一点,重叠的标签几乎都是这一步欠的账。
    """
    ids = [n["id"] for n in nodes]
    if not ids:
        return {}
    rng = random.Random(SEED)
    pos = {i: (rng.uniform(-500, 500), rng.uniform(-500, 500)) for i in ids}
    degree = {i: 0 for i in ids}
    for e in edges:
        degree[e["from"]] = degree.get(e["from"], 0) + 1
        degree[e["to"]] = degree.get(e["to"], 0) + 1

    index = {i: k for k, i in enumerate(ids)}
    pairs = [(e["from"], e["to"]) for e in edges]

    # -- 阶段 1:力导向 ---------------------------------------------------
    k_repel = 180_000.0   # 斥力强度
    k_spring = 0.06       # 弹簧刚度
    rest_len = 160.0      # 弹簧自然长度
    max_move = 40.0       # 单轮位移上限,防越推越飞

    for step in range(400):
        fx = {i: 0.0 for i in ids}
        fy = {i: 0.0 for i in ids}
        # 斥力:所有点对
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                ia, ib = ids[a], ids[b]
                dx = pos[ia][0] - pos[ib][0]
                dy = pos[ia][1] - pos[ib][1]
                dist = math.hypot(dx, dy)
                if dist < 1e-6:
                    # 完全重合的两点:给一个确定方向的微推
                    dx, dy, dist = 1.0, 0.0, 1.0
                f = k_repel / (dist * dist)
                ux, uy = dx / dist, dy / dist
                fx[ia] += f * ux; fy[ia] += f * uy
                fx[ib] -= f * ux; fy[ib] -= f * uy
        # 弹簧:连线把两端拉近
        for a, b in pairs:
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            dist = math.hypot(dx, dy)
            if dist < 1e-6:
                dx, dy, dist = 1.0, 0.0, 1.0
            f = k_spring * (dist - rest_len)
            ux, uy = dx / dist, dy / dist
            fx[a] -= f * ux; fy[a] -= f * uy
            fx[b] += f * ux; fy[b] += f * uy
        # 边交叉惩罚:两条边相交时,把其中一条边的两端沿垂直方向平移,
        # 整条线让开另一条。力度温和,跟斥力/弹簧一起迭代找平衡。
        k_cross = 35.
        for i in range(len(pairs)):
            a1, a2 = pairs[i]
            for j in range(i + 1, len(pairs)):
                b1, b2 = pairs[j]
                if a1 in (b1, b2) or a2 in (b1, b2):
                    continue  # 共端点不算交叉
                p1, p2 = pos[a1], pos[a2]
                p3, p4 = pos[b1], pos[b2]
                if not _segments_cross(p1, p2, p3, p4):
                    continue
                # 把 a 边两端沿"a 中点远离 b 中点"方向同向平移
                mid_a = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
                mid_b = ((p3[0] + p4[0]) / 2, (p3[1] + p4[1]) / 2)
                nx = mid_a[0] - mid_b[0]
                ny = mid_a[1] - mid_b[1]
                nl = math.hypot(nx, ny)
                if nl < 1e-6:
                    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                    ln = math.hypot(dx, dy) or 1.
                    nx, ny = -dy / ln, dx / ln
                else:
                    nx, ny = nx / nl, ny / nl
                fx[a1] += k_cross * nx; fy[a1] += k_cross * ny
                fx[a2] += k_cross * nx; fy[a2] += k_cross * ny
        # 阻尼位移
        cooling = 1.0 - step / 500
        for i in ids:
            mx = max(-max_move, min(max_move, fx[i] * cooling))
            my = max(-max_move, min(max_move, fy[i] * cooling))
            pos[i] = (pos[i][0] + mx, pos[i][1] + my)

    # -- 阶段 2:去重叠 ---------------------------------------------------
    # 安全间距:节点半径 + 标签宽度的一半。标签是重叠的视觉主体。
    radius = {i: (26 if nodes[index[i]]["kind"] == "article" else 18) for i in ids}
    min_gap = 95.  # 点对点最小距离;确保标签(最长 14 字)不叠
    for _ in range(300):
        moved = False
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                ia, ib = ids[a], ids[b]
                dx = pos[ia][0] - pos[ib][0]
                dy = pos[ia][1] - pos[ib][1]
                dist = math.hypot(dx, dy)
                need = radius[ia] + radius[ib] + min_gap
                if dist < need:
                    if dist < 1e-6:
                        # 同一点:按 id 排序给固定方向,保持确定性
                        if ia < ib:
                            dx, dy, dist = 1.0, 0.0, 1.0
                        else:
                            dx, dy, dist = -1.0, 0.0, 1.0
                    push = (need - dist) / 2 + 0.5
                    ux, uy = dx / dist, dy / dist
                    pos[ia] = (pos[ia][0] + ux * push, pos[ia][1] + uy * push)
                    pos[ib] = (pos[ib][0] - ux * push, pos[ib][1] - uy * push)
                    moved = True
        if not moved:
            break

    return pos


    return pos


# ---------------------------------------------------------------------------
# HTML 模板(内嵌 vis-network + 数据 + 交互)
# ---------------------------------------------------------------------------

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>卡片盒 · 星图</title>
<style>
  :root {
    --bg: #0d1117;
    --panel-bg: rgba(22, 27, 34, 0.92);
    --border: rgba(240, 246, 252, 0.12);
    --text: #e6edf3;
    --text-dim: #8b949e;
    --accent: #58a6ff;
    --draft: #f0883e;
    --promoted: #3fb950;
    --human: #58a6ff;
    --article: #bc8cff;
  }
  html, body {
    margin: 0; height: 100%; overflow: hidden;
    font-family: -apple-system, "PingFang SC", sans-serif;
    background: var(--bg); color: var(--text);
  }
  #network { height: 100%; }

  /* 顶栏 */
  #topbar {
    position: fixed; top: 0; left: 0; right: 0; z-index: 10;
    display: flex; align-items: baseline; gap: 16px;
    padding: 14px 22px; box-sizing: border-box;
    background: linear-gradient(to bottom, rgba(13,17,23,.92), transparent);
    pointer-events: none;  /* 不挡图 */
  }
  #topbar h1 { font-size: 17px; margin: 0; font-weight: 600; letter-spacing: .5px; }
  #topbar .stats { color: var(--text-dim); font-size: 12.5px; }
  #topbar .stats b { color: var(--text); font-weight: 500; }

  /* 图例 */
  #legend {
    position: fixed; left: 14px; bottom: 40px; z-index: 10;
    display: flex; flex-direction: column; gap: 7px;
    padding: 12px 14px; font-size: 12px; color: var(--text-dim);
    background: var(--panel-bg); border: 1px solid var(--border);
    border-radius: 10px; backdrop-filter: blur(8px);
  }
  #legend .item { display: flex; align-items: center; gap: 8px; }
  #legend .swatch { width: 10px; height: 10px; border-radius: 50%; }
  #legend .swatch.article { border-radius: 2px; transform: rotate(45deg); }

  #hint {
    position: fixed; left: 14px; bottom: 12px; z-index: 10;
    color: var(--text-dim); font-size: 11.5px; opacity: .8;
  }

  /* 详情面板 */
  #panel {
    position: fixed; top: 0; right: -440px; width: 420px; height: 100%;
    background: var(--panel-bg); border-left: 1px solid var(--border);
    overflow-y: auto; padding: 24px 22px; box-sizing: border-box;
    transition: right .28s cubic-bezier(.4,0,.2,1);
    font-size: 13.5px; line-height: 1.75; backdrop-filter: blur(14px);
    z-index: 20;
  }
  #panel.open { right: 0; }
  #panel::-webkit-scrollbar { width: 8px; }
  #panel::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
  #panel .close {
    position: absolute; top: 14px; right: 14px; cursor: pointer;
    font-size: 20px; color: var(--text-dim); line-height: 1;
    padding: 4px 8px; border-radius: 6px;
  }
  #panel .close:hover { color: var(--text); background: rgba(240,246,252,.08); }
  #panel h2 { font-size: 17px; margin: 0 0 10px; line-height: 1.45;
              padding-right: 28px; font-weight: 600; }
  #panel .meta { color: var(--text-dim); font-size: 12px; margin-bottom: 16px;
                 word-break: break-all; line-height: 2; }
  #panel .badge {
    display: inline-block; padding: 1px 9px; border-radius: 10px;
    font-size: 11px; margin-right: 5px; border: 1px solid transparent;
    vertical-align: 1px;
  }
  #panel .badge.auto { color: var(--draft); border-color: var(--draft);
                       background: rgba(240,136,62,.12); }
  #panel .badge.human { color: var(--human); border-color: var(--human);
                        background: rgba(88,166,255,.12); }
  #panel .badge.draft { color: var(--text-dim); border-color: var(--text-dim);
                        background: rgba(139,148,158,.12); }
  #panel .badge.promoted { color: var(--promoted); border-color: var(--promoted);
                           background: rgba(63,185,80,.12); }
  /* 正文:舒适阅读版式 */
  #panel .body-text {
    font-size: 14px; line-height: 1.9; color: var(--text);
    letter-spacing: .2px; margin: 10px 0 16px;
  }
  /* 草稿全文:轻量 markdown 渲染后的排版 */
  #panel .article-body { margin: 8px 0 16px; }
  #panel .article-body h1 {
    font-size: 17px; margin: 22px 0 10px; padding-bottom: 8px;
    border-bottom: 1px solid var(--border); font-weight: 600;
  }
  #panel .article-body h2 {
    font-size: 15px; margin: 20px 0 8px; font-weight: 600;
    color: var(--text);
  }
  #panel .article-body p { font-size: 13.5px; line-height: 1.9;
                           margin: 0 0 12px; }
  #panel .article-body li { font-size: 13.5px; line-height: 1.9;
                            margin: 0 0 6px; }
  #panel .article-body ul, #panel .article-body ol { padding-left: 22px;
                                                     margin: 0 0 12px; }
  #panel .article-body hr { border: none; border-top: 1px solid var(--border);
                            margin: 18px 0; }
  #panel .article-body strong { color: #fff; font-weight: 600; }
  #panel .sec {
    border-left: 3px solid var(--article); padding: 2px 0 2px 12px;
    margin: 12px 0;
  }
  #panel .sec b { font-size: 13.5px; }
  #panel .sec .cards { color: var(--text-dim); font-size: 11.5px; margin: 2px 0 4px; }
  #panel .sec .cards span { cursor: pointer; }
  #panel .sec .cards span:hover { color: var(--accent); text-decoration: underline; }
  #panel .sec .angle { font-size: 12.5px; color: var(--text-dim);
                       line-height: 1.75; margin-top: 4px; }
  #panel .label { color: var(--text-dim); font-size: 11px; letter-spacing: 1px;
                  margin: 20px 0 6px; text-transform: uppercase; }
  #panel p.thesis { font-size: 14px; line-height: 1.85; margin: 4px 0 8px;
                    color: var(--text); }

  /* 空状态 */
  #empty {
    position: fixed; inset: 0; display: none;
    align-items: center; justify-content: center; flex-direction: column;
    color: var(--text-dim); gap: 8px;
  }
  #empty .big { font-size: 42px; }
  #empty.show { display: flex; }
</style>
</head>
<body>
<div id="network"></div>

<div id="topbar">
  <h1>卡片盒 · 星图</h1>
  <div class="stats" id="stats"></div>
</div>

<div id="legend">
  <div class="item"><span class="swatch" style="background:var(--draft)"></span>草稿(inbox)</div>
  <div class="item"><span class="swatch" style="background:var(--promoted)"></span>已转正</div>
  <div class="item"><span class="swatch" style="background:var(--human)"></span>人写</div>
  <div class="item"><span class="swatch article" style="background:var(--article)"></span>文章</div>
  <div class="item" style="margin-top:4px;opacity:.75">— 实线:链接 &nbsp;┄ 虚线:装配</div>
</div>

<div id="hint">拖拽移动 · 滚轮缩放 · 点击节点看全文 · 悬停连线看链接理由 · 点击节点后按 0 聚焦</div>

<div id="panel">
  <span class="close" onclick="closePanel()">×</span>
  <div id="panel-content"></div>
</div>

<div id="empty"><div class="big">📦</div><div>卡片盒是空的</div><div style="font-size:12px">zkt ingest 一点东西进来吧</div></div>

<script>__VIS_JS__</script>
<script>
const DATA = __DATA__;

const KIND_STYLE = {
  draft:    {color: "#f0883e", glow: "rgba(240,136,62,.35)"},
  promoted: {color: "#3fb950", glow: "rgba(63,185,80,.35)"},
  human:    {color: "#58a6ff", glow: "rgba(88,166,255,.35)"},
  article:  {color: "#bc8cff", glow: "rgba(188,140,255,.4)"},
};

const nodes = new vis.DataSet(DATA.nodes.map(n => ({
  id: n.id,
  label: n.label,
  x: n.x,
  y: n.y,
  shape: n.kind === "article" ? "diamond" : (n.kind === "human" ? "hexagon" : "dot"),
  color: {
    background: KIND_STYLE[n.kind].color,
    border: KIND_STYLE[n.kind].color,
    highlight: {background: "#e6edf3", border: KIND_STYLE[n.kind].color},
    hover: {background: "#e6edf3", border: KIND_STYLE[n.kind].color},
  },
  size: n.kind === "article" ? 16 : 11,
  borderWidth: n.kind === "article" ? 2 : 1,
  shadow: {enabled: true, color: KIND_STYLE[n.kind].glow, size: 18, x: 0, y: 0},
  font: {face: "-apple-system, PingFang SC", size: 12, color: "#8b949e",
         strokeWidth: 3, strokeColor: "rgba(13,17,23,.85)"},
  title: n.title,
  _data: n,
})));

const edges = new vis.DataSet(DATA.edges.map(e => {
  const hasRound = typeof e.roundness === "number";
  return {
    from: e.from, to: e.to,
    arrows: {to: {scaleFactor: .6}},
    dashes: e.kind === "assemble",
    width: e.kind === "assemble" ? 1 : 1.4,
    color: {color: e.kind === "assemble" ? "rgba(188,140,255,.35)" : "rgba(139,148,158,.4)",
            highlight: "#ff7b72", hover: "#ff7b72"},
    title: e.why,
    _kind: e.kind,
    // 平行边用曲线错开;单条边保持直线,视觉干净
    smooth: hasRound
      ? {enabled: true, type: "curvedCW", roundness: e.roundness}
      : {enabled: false},
  };
}));

// 顶栏统计
const counts = {draft: 0, promoted: 0, human: 0, article: 0};
DATA.nodes.forEach(n => counts[n.kind]++);
const linkCount = DATA.edges.filter(e => e.kind === "link").length;
document.getElementById("stats").innerHTML =
  `<b>${DATA.nodes.length}</b> 张卡 · <b>${linkCount}</b> 条链接 · `
  + `<b>${counts.promoted}</b> 已转正 · <b>${counts.article}</b> 篇文章`;

if (DATA.nodes.length === 0) {
  document.getElementById("empty").classList.add("show");
}

const container = document.getElementById("network");
const network = new vis.Network(
  container,
  {nodes: nodes, edges: edges},
  {
    interaction: {hover: true, hoverConnectedEdges: true,
                  tooltipDelay: 120, keyboard: true},
    // 布局已在生成时算定,前端不跑物理——刷新必得同一张图
    physics: {enabled: false},
    edges: {smooth: {enabled: false}, selectionWidth: 2},
    nodes: {mass: 2},
  }
);

// 拖拽单个节点是允许的(局部微调),但松手后不重启物理
network.on("dragEnd", () => network.stopSimulation());

// 详情面板
const panel = document.getElementById("panel");
const content = document.getElementById("panel-content");

function esc(s) {
  return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;");
}

// 轻量 markdown 渲染:标题/加粗/列表/分隔线。够展示草稿用,不求全。
function mdToHtml(md) {
  const lines = esc(md).split("\n");
  let html = "", inList = false;
  for (const line of lines) {
    const t = line.trim();
    if (/^###\s+/.test(t))      { html += (inList ? closeList() : "") + `<h2>${t.slice(4)}</h2>`; }
    else if (/^##\s+/.test(t))  { html += (inList ? closeList() : "") + `<h2>${t.slice(3)}</h2>`; }
    else if (/^#\s+/.test(t))   { html += (inList ? closeList() : "") + `<h1>${t.slice(2)}</h1>`; }
    else if (/^(-{3,}|\*{3,})$/.test(t)) { html += (inList ? closeList() : "") + "<hr>"; }
    else if (/^[-*]\s+/.test(t)) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(t.slice(2))}</li>`;
    }
    else if (/^\d+\.\s+/.test(t)) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(t.replace(/^\d+\.\s+/, ""))}</li>`;
    }
    else if (t === "")          { html += (inList ? closeList() : "") + ""; }
    else                        { html += (inList ? closeList() : "") + `<p>${inline(t)}</p>`; }
  }
  if (inList) html += closeList();
  return html;

  function closeList() { inList = false; return "</ul>"; }
  function inline(s) {
    return s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
            .replace(/`(.+?)`/g, "<code>$1</code>");
  }
}

function showCard(n) {
  const badge = n.auto
    ? `<span class="badge auto">auto</span>`
    : `<span class="badge human">人写</span>`;
  const status = n.status === "草稿(inbox)"
    ? `<span class="badge draft">草稿</span>`
    : `<span class="badge promoted">已转正</span>`;
  const src = n.source
    ? `<div class="meta" style="margin-bottom:0">来源: ${esc(n.source)}</div>` : "";
  content.innerHTML =
    `<h2>${esc(n.title)}</h2>`
    + `<div class="meta">${badge}${status}<br>${esc(n.id)} · ${esc(n.filename)}</div>`
    + src
    + `<div class="label">正文</div>`
    + `<div class="body-text">${esc(n.body) || "(空)"}</div>`;
}

function showArticle(n) {
  let secs = "";
  for (const s of (n.sections || [])) {
    const cards = s.cards.map(c =>
      `<span onclick="jumpTo('${c}')">${esc(c.slice(-6))}</span>`).join(" ");
    secs += `<div class="sec"><b>${esc(s.title)}</b>`
          + `<div class="cards">装配: ${cards}</div>`
          + `<div class="angle">${esc(s.angle)}</div></div>`;
  }
  // 草稿全文去掉首行大标题(面板 h2 已有),避免重复
  const draftBody = (n.draft || "").replace(/^#\s+.+\n+/, "");
  content.innerHTML =
    `<h2>${esc(n.title)}</h2>`
    + `<div class="meta"><span class="badge auto">装配产物</span>drafts/</div>`
    + `<div class="label">论点</div>`
    + `<p class="thesis">${esc(n.thesis)}</p>`
    + `<div class="label">大纲</div>`
    + secs
    + `<div class="label">草稿全文</div>`
    + `<div class="article-body">${mdToHtml(draftBody)}</div>`;
}

network.on("click", function (params) {
  if (params.nodes.length === 0) { closePanel(); return; }
  const n = nodes.get(params.nodes[0])._data;
  if (n.kind === "article") { showArticle(n); }
  else { showCard(n); }
  panel.classList.add("open");
});

// 从文章面板点卡片 id,跳到那张卡
window.jumpTo = function (cardId) {
  network.selectNodes([cardId]);
  network.focus(cardId, {scale: 1.1, animation: {duration: 400}});
  const n = nodes.get(cardId);
  if (n) { showCard(n._data); }
};

function closePanel() { panel.classList.remove("open"); }
</script>
</body>
</html>
"""


def build_html() -> Path:
    """组装自包含 HTML 并写出。"""
    data = json.dumps(collect_data(), ensure_ascii=False)
    vis_js = VENDOR_JS.read_text(encoding="utf-8")
    html = TEMPLATE.replace("__VIS_JS__", vis_js).replace("__DATA__", data)
    OUTPUT.write_text(html, encoding="utf-8")
    return OUTPUT


def cmd_graph(argv: list[str]) -> int:
    """zkt graph —— 生成可视化 HTML 并打开。"""
    path = build_html()
    print(f"已生成: {path}")
    import subprocess
    subprocess.run(["open", str(path)])  # macOS
    return 0
