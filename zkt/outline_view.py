"""outline_view.py —— 把 outline.json 渲染成可操作的本地 HTML。

zkt outline --view 生成 zk/drafts/outline.html:
- 拖拽调整节的顺序
- 点击卡片看原文
- 页面上直接改标题/论点/各节内容,点"导出"下载新的 outline.json
"""

import json

from card import zk_home

DRAFTS_DIR = zk_home() / "drafts"
CARDS_DIR = zk_home() / "cards"


def load_cards() -> dict:
    cards = {}
    for directory in (CARDS_DIR, zk_home() / "inbox"):
        for path in directory.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            meta, body = {}, ""
            if lines and lines[0].strip() == "---":
                end = lines.index("---", 1)
                for line in lines[1:end]:
                    if ":" in line:
                        key, _, val = line.partition(":")
                        meta[key.strip()] = val.strip()
                body = "\n".join(lines[end + 1:]).strip()
            cards[meta.get("id", path.stem)] = {
                "title": meta.get("title", ""),
                "body": body.strip(),
                "inbox": directory != CARDS_DIR,
            }
    return cards


TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>大纲审阅 — __TITLE__</title>
<style>
  :root { --line: #ddd; --accent: #4a6fa5; --bg: #fafafa; }
  * { box-sizing: border-box; }
  body { font-family: "PingFang SC", sans-serif; max-width: 860px; margin: 0 auto; padding: 24px; background: var(--bg); color: #222; }
  h1 { font-size: 22px; }
  .thesis { background: #fff; border-left: 4px solid var(--accent); padding: 12px 16px; margin-bottom: 24px; }
  .section { background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 16px; margin-bottom: 12px; cursor: grab; }
  .section.dragging { opacity: .4; }
  .section .num { color: var(--accent); font-weight: bold; margin-right: 8px; }
  .sec-title { font-size: 16px; font-weight: 600; width: 100%; border: none; border-bottom: 1px dashed transparent; background: transparent; font-family: inherit; }
  .sec-title:focus { border-bottom-color: var(--accent); outline: none; }
  .angle { width: 100%; border: none; background: transparent; color: #555; font-size: 13px; font-family: inherit; resize: vertical; min-height: 40px; margin-top: 6px; }
  .angle:focus { outline: 1px dashed var(--accent); }
  .cards { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { background: #eef3fa; color: var(--accent); border-radius: 12px; padding: 2px 10px; font-size: 12px; cursor: pointer; }
  .chip:hover { background: #dbe6f3; }
  .addcard { border: 1px dashed #bbb; color: #888; border-radius: 12px; padding: 2px 10px; font-size: 12px; cursor: pointer; background: none; }
  .del-sec { float: right; border: none; background: none; color: #c66; cursor: pointer; font-size: 13px; }
  .card-panel { display: none; background: #fffbe8; border: 1px solid #e8d48a; border-radius: 8px; padding: 14px; margin: 12px 0; font-size: 14px; }
  .card-panel h3 { margin: 0 0 8px; font-size: 15px; }
  .card-panel .close { float: right; cursor: pointer; border: none; background: none; }
  .toolbar { position: sticky; bottom: 0; background: var(--bg); padding: 12px 0; border-top: 1px solid var(--line); display: flex; gap: 12px; }
  button.primary { background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 8px 20px; cursor: pointer; font-size: 14px; }
  .add-sec { border: 1px dashed #aaa; background: none; border-radius: 8px; padding: 10px; width: 100%; cursor: pointer; color: #888; }
  .hint { color: #999; font-size: 12px; }
</style>
</head>
<body>
<h1>大纲:<input class="sec-title" id="doc-title" style="font-size:22px;font-weight:700" value=""></h1>
<p class="hint">拖拽卡片条调整节的顺序 · 点击卡片名看原文 · 所有输入框可直接编辑</p>
<div class="thesis">论点:<textarea class="angle" id="doc-thesis" style="color:#222;font-size:14px"></textarea></div>
<div id="sections"></div>
<button class="add-sec" id="add-sec">+ 加一节</button>
<div class="card-panel" id="card-panel"></div>
<div class="toolbar">
  <button class="primary" id="export">导出 outline.json</button>
  <span class="hint" id="status"></span>
</div>

<script>
const DATA = __DATA__;
const state = DATA.outline;
document.getElementById("doc-title").value = state.title;
document.getElementById("doc-thesis").value = state.thesis;

function render() {
  const box = document.getElementById("sections");
  box.innerHTML = "";
  state.sections.forEach((sec, i) => {
    const div = document.createElement("div");
    div.className = "section";
    div.draggable = true;
    div.innerHTML = `<span class="num">${i + 1}</span><button class="del-sec">删节</button>
      <input class="sec-title" value="${esc(sec.title)}" placeholder="本节标题">
      <textarea class="angle" placeholder="这一节讲什么、怎么衔接">${esc(sec.angle || "")}</textarea>
      <div class="cards"></div>`;
    div.querySelector(".sec-title").oninput = e => sec.title = e.target.value;
    div.querySelector(".angle").oninput = e => sec.angle = e.target.value;
    div.querySelector(".del-sec").onclick = () => { state.sections.splice(i, 1); render(); };
    const cardsBox = div.querySelector(".cards");
    (sec.cards || []).forEach(cid => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = (DATA.cards[cid] && DATA.cards[cid].title) || cid;
      chip.title = cid + (DATA.cards[cid] && DATA.cards[cid].inbox ? "(待转正)" : "") + "(点击看原文,再次点击收起)";
      chip.onclick = () => showCard(cid);
      cardsBox.appendChild(chip);
    });
    const add = document.createElement("button");
    add.className = "addcard";
    add.textContent = "+挂卡片";
    add.onclick = () => pickCard(cid => { if (cid && !sec.cards.includes(cid)) { sec.cards.push(cid); render(); } });
    cardsBox.appendChild(add);
    div.ondragstart = e => { dragFrom = i; div.classList.add("dragging"); };
    div.ondragend = () => div.classList.remove("dragging");
    div.ondragover = e => e.preventDefault();
    div.ondrop = e => {
      e.preventDefault();
      if (dragFrom === null || dragFrom === i) return;
      const [moved] = state.sections.splice(dragFrom, 1);
      state.sections.splice(i, 0, moved);
      dragFrom = null;
      render();
    };
    box.appendChild(div);
  });
}
let dragFrom = null;
function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;"); }
function showCard(cid) {
  const panel = document.getElementById("card-panel");
  const card = DATA.cards[cid];
  if (!card) { panel.style.display = "none"; return; }
  if (panel.dataset.cid === cid && panel.style.display === "block") { panel.style.display = "none"; return; }
  panel.dataset.cid = cid;
  panel.innerHTML = `<button class="close">收起 ✕</button><h3>${esc(card.title)} <span class="hint">${cid}</span></h3><p>${esc(card.body)}</p>`;
  panel.querySelector(".close").onclick = () => panel.style.display = "none";
  panel.style.display = "block";
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
function pickCard(cb) {
  const ids = Object.keys(DATA.cards).filter(id => !state.sections.some(s => (s.cards || []).includes(id)));
  const choice = prompt("输入要挂的卡片 id:\\n" + ids.map(id => id + " " + (DATA.cards[id] ? DATA.cards[id].title : "")).join("\\n"));
  cb(choice && choice.trim());
}
document.getElementById("doc-title").oninput = e => state.title = e.target.value;
document.getElementById("doc-thesis").oninput = e => state.thesis = e.target.value;
document.getElementById("add-sec").onclick = () => {
  state.sections.push({ title: "新的一节", cards: [], angle: "" });
  render();
};
document.getElementById("export").onclick = () => {
  const blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "outline.json";
  a.click();
  document.getElementById("status").textContent = "已下载 outline.json,请覆盖 zk/drafts/outline.json";
};
render();
</script>
</body>
</html>
"""


def cmd_outline_view() -> int:
    outline_path = DRAFTS_DIR / "outline.json"
    if not outline_path.exists():
        print("没有 drafts/outline.json,先跑 zkt outline。")
        return 1
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    html = (
        TEMPLATE.replace("__TITLE__", outline.get("title", ""))
        .replace("__DATA__", json.dumps(
            {"outline": outline, "cards": load_cards()}, ensure_ascii=False))
    )
    out = DRAFTS_DIR / "outline.html"
    out.write_text(html, encoding="utf-8")
    print(f"大纲页面已生成: {out}")
    print("浏览器打开它,审阅/修改后点「导出 outline.json」,覆盖 zk/drafts/outline.json 即可。")
    return 0
