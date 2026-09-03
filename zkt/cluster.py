"""cluster.py —— 卡片簇发现:找连通分量,判断哪个簇够格开写作。"""

from __future__ import annotations

from card import Card, load_all


def find_clusters(min_size: int = 3) -> list[list[Card]]:
    """并查集找链接图的连通分量。min_size 以下的簇不返回(不够开写作)。"""
    cards = load_all()
    by_id = {c.id: c for c in cards}

    parent = {c.id: c.id for c in cards}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # 路径压缩
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for card in cards:
        for link in card.links:
            if link.to in by_id:  # 死链已被宪法拦住,这里防御一下
                union(card.id, link.to)

    groups: dict[str, list[Card]] = {}
    for card in cards:
        groups.setdefault(find(card.id), []).append(card)

    clusters = [sorted(g, key=lambda c: c.id) for g in groups.values()]
    # 大簇在前,同大小按 id 稳定排序
    clusters.sort(key=lambda g: (-len(g), g[0].id))
    return [g for g in clusters if len(g) >= min_size]


def describe_cluster(cluster: list[Card]) -> str:
    """给人看的簇描述:每张卡一行 + 簇内链接数。"""
    ids = {c.id for c in cluster}
    internal_links = sum(
        len([l for l in c.links if l.to in ids]) for c in cluster
    )
    lines = [
        f"簇内 {len(cluster)} 张卡,{internal_links} 条内部链接:",
    ]
    for c in cluster:
        tag = " [auto]" if c.auto else ""
        lines.append(f"  {c.id}{tag}  {c.title}")
    return "\n".join(lines)


def cmd_clusters(argv: list[str]) -> int:
    """zkt clusters —— 找够格的簇(≥3 张互链),每簇列卡片清单。"""
    found = find_clusters()
    if not found:
        print("没有够格的簇(至少 3 张卡互链)。先养盒。")
        return 0
    for c in found:
        print(describe_cluster(c))
        print()
    return 0
