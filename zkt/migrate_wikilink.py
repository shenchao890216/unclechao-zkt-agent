"""migrate_wikilink.py —— 一次性迁移:frontmatter links → 正文 wikilink。

python3 migrate_wikilink.py
幂等:正文已含 [[id 的文件跳过。
"""

from pathlib import Path

import frontmatter
import yaml

ROOT = Path(__file__).resolve().parent.parent
DIRS = [ROOT / "zk" / "inbox", ROOT / "zk" / "cards"]


def migrate(path: Path) -> str:
    post = frontmatter.load(path)
    links = post.metadata.get("links", [])
    if not links:
        return "skip(无 links)"
    if "[[" in post.content:
        return "skip(正文已有 wikilink)"

    lines = [f"→ [[{l['to']}|{l['why']}]]" for l in links]
    post.content = post.content.rstrip() + "\n\n" + "\n".join(lines) + "\n"
    post.metadata.pop("links", None)
    fm = yaml.safe_dump(
        post.metadata, allow_unicode=True, default_flow_style=False, sort_keys=False
    ).strip()
    path.write_text(f"---\n{fm}\n---\n\n{post.content}", encoding="utf-8")
    return f"migrated({len(links)} 条链接)"


def main() -> None:
    for directory in DIRS:
        for path in sorted(directory.glob("*.md")):
            print(f"{path.relative_to(ROOT)}: {migrate(path)}")


if __name__ == "__main__":
    main()
