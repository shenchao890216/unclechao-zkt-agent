"""fetch.py —— URL 抓取:把网页变成纯文本,喂给 agent。

抓取是确定性代码的活(不需要判断力),所以不交给模型。
"""

from __future__ import annotations

import html2text
import httpx


def fetch_url(url: str, max_chars: int = 20000) -> str:
    """抓网页,转 markdown 文本。超长截断(agent 消化不了那么长)。"""
    # 浏览器 UA,避免被一些网站拒掉
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    response = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
    response.raise_for_status()

    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0  # 不自动换行,保持段落完整

    text = converter.handle(response.text)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[...已截断,原文 {len(text)} 字符]"
    return text.strip()
