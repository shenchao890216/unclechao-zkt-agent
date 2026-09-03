"""卡片盒存储层:读、写、校验。

宪法(校验规则)写在这里,不写在 prompt 里——
违反规则的卡片在工具层就被拒收,模型永远没机会存进盒。
"""

from __future__ import annotations

import datetime
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter
import yaml

# 项目根目录(zk/ 的父目录),也是未配置时的默认盒子位置
ROOT = Path(__file__).resolve().parent.parent
ZKTRC = Path.home() / ".zktrc"


def zk_home() -> Path:
    """盒子根目录。优先级:ZK_HOME 环境变量 > ~/.zktrc > 默认 ROOT/zk。"""
    env = os.environ.get("ZK_HOME")
    if env:
        return Path(env).expanduser()
    if ZKTRC.exists():
        try:
            home = json.loads(ZKTRC.read_text(encoding="utf-8")).get("home")
            if home:
                return Path(home).expanduser()
        except (json.JSONDecodeError, OSError):
            pass
    return ROOT / "zk"


def inbox_dir() -> Path:
    return zk_home() / "inbox"


def cards_dir() -> Path:
    return zk_home() / "cards"


def drafts_dir() -> Path:
    return zk_home() / "drafts"

# 原子性启发式:正文超过这个字数只警告,不拒绝
MAX_BODY_CHARS = 800

# id 格式:日期 + 6 位十六进制,如 20260826-a1b2c3
ID_PATTERN = re.compile(r"^\d{8}-[0-9a-f]{6}$")

# 正文内 wikilink:Obsidian 别名语法 [[id|why]],why 可省略
WIKILINK_PATTERN = re.compile(r"\[\[(\d{8}-[0-9a-f]{6})(?:\|([^\]]*))?\]\]")


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class Link:
    """一条链接:指向谁(to),为什么链(why)。why 必填。"""

    to: str
    why: str


@dataclass
class Card:
    """一张卡片:frontmatter(id/title/source/links/auto)+ 正文。"""

    id: str
    title: str
    body: str = ""
    source: str = ""
    links: list[Link] = field(default_factory=list)
    auto: bool = False          # true = agent 存的;false = 人写的
    path: Path | None = None    # 这张卡在磁盘上的位置

    # -- 写盘 ---------------------------------------------------------------

    def to_disk(self) -> str:
        """序列化成 markdown 文本(frontmatter + 正文)。

        frontmatter 用 yaml.safe_dump 序列化——绝不手工拼字符串。
        曾经的教训:标题含英文双引号时手拼 YAML 炸掉,写时成功读时爆。
        """
        meta: dict = {"id": self.id, "title": self.title}
        if self.source:
            meta["source"] = self.source
        if self.auto:
            meta["auto"] = True

        fm = yaml.safe_dump(
            meta, allow_unicode=True, default_flow_style=False, sort_keys=False
        ).strip()
        return f"---\n{fm}\n---\n\n{self.body}\n"

    def save(self, inbox: bool = True) -> Path:
        """写盘。默认落 inbox(草稿区);promote 时才搬进 cards。"""
        if self.path is not None:
            target = self.path
        else:
            directory = inbox_dir() if inbox else cards_dir()
            target = directory / f"{self.id}.md"
        target.write_text(self.to_disk(), encoding="utf-8")
        self.path = target
        return target

    # -- 读盘 ---------------------------------------------------------------

    @classmethod
    def from_file(cls, path: Path) -> "Card":
        """从磁盘读一张卡。格式非法时抛 ValueError。"""
        post = frontmatter.load(path)
        meta = post.metadata
        try:
            card = cls(
                id=str(meta["id"]),
                title=str(meta["title"]),
                body=post.content.strip(),
                source=str(meta.get("source", "")),
                links=[
                    Link(to=m.group(1), why=(m.group(2) or "").strip())
                    for m in WIKILINK_PATTERN.finditer(post.content)
                ],
                auto=bool(meta.get("auto", False)),
            )
        except KeyError as e:
            raise ValueError(f"{path.name}: 缺少必填字段 {e}") from e
        card.path = path
        return card

    # -- 链接 ---------------------------------------------------------------

    def add_link(self, to: str, why: str) -> list[str]:
        """给这张卡加一条链接。返回错误列表(空 = 成功)。

        宪法在这里把门:目标必须存在、理由必须非空、不许自链、不许重复。
        """
        errors: list[str] = []
        if to == self.id:
            errors.append("不能链接自己")
        if to not in all_ids():
            errors.append(f"死链: {to} 不存在")
        if not why.strip():
            errors.append("why 为空: 没理由的链接不算链接")
        existing_tos = {link.to for link in self.links}
        if to in existing_tos:
            errors.append(f"到 {to} 的链接已存在")
        if errors:
            return errors
        self.links.append(Link(to=to, why=why))
        self.body = self.body.rstrip() + f"\n\n→ [[{to}|{why}]]\n"
        self.save()  # 覆写自己的文件
        return []

    # -- 校验 ---------------------------------------------------------------

    def validate(self, known_ids: set[str]) -> list[str]:
        """返回违规列表。空列表 = 合法。

        known_ids: 盒中已存在的所有卡片 id。死链校验靠它。
        """
        errors: list[str] = []

        if not self.id:
            errors.append("id 为空")
        elif not ID_PATTERN.match(self.id):
            errors.append(
                f"id 格式应为 YYYYMMDD-6位十六进制(如 20260826-a1b2c3): {self.id}"
            )
        if not self.title:
            errors.append("title 为空")
        if not self.body:
            errors.append("正文为空")

        for link in self.links:
            if not link.to:
                errors.append("存在 to 为空的链接")
            elif link.to not in known_ids:
                errors.append(f"死链: {link.to} 不存在")
            if not link.why.strip():
                errors.append(f"链接 {link.to} 缺 why(没理由的链接不算链接)")

        return errors

    def warnings(self) -> list[str]:
        """警告:不阻止存入,但人审核时应该看一眼。"""
        warns: list[str] = []
        if len(self.body) > MAX_BODY_CHARS:
            warns.append(
                f"正文 {len(self.body)} 字,超过 {MAX_BODY_CHARS} 字启发式阈值,"
                "可能不够原子——检查是否一卡多观点"
            )
        return warns

    # -- 工厂 ----------------------------------------------------------------

    @staticmethod
    def new_id() -> str:
        """日期 + 短随机串,如 20260826-a1b2c3。"""
        today = datetime.date.today().strftime("%Y%m%d")
        rand = secrets.token_hex(3)  # 6 个十六进制字符
        return f"{today}-{rand}"


def all_ids() -> set[str]:
    """全盒已有 id 集合(inbox + cards),死链校验的依据。"""
    ids = set()
    for directory in (inbox_dir(), cards_dir()):
        for path in directory.glob("*.md"):
            ids.add(path.stem)
    return ids


def load_all() -> list[Card]:
    """读全盒。读不动的卡(格式非法)也返回,带 errors 标记。"""
    cards: list[Card] = []
    for directory in (inbox_dir(), cards_dir()):
        for path in sorted(directory.glob("*.md")):
            try:
                cards.append(Card.from_file(path))
            except ValueError as e:
                # 格式烂到读不出来的卡:包装成一张空卡,让 check 能报告它
                cards.append(Card(id=path.stem, title="<无法解析>", path=path))
    return cards


def search_cards(keyword: str) -> list[Card]:
    """按关键词搜卡:匹配标题或正文,大小写不敏感。"""
    keyword = keyword.lower()
    results = []
    for card in load_all():
        haystack = (card.title + "\n" + card.body).lower()
        if keyword in haystack:
            results.append(card)
    return results
