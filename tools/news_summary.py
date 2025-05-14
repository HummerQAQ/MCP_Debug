# tools/news_summary.py
from fastmcp import FastMCP
import os, random, re, httpx, traceback
from typing import List, Dict
from bs4 import BeautifulSoup

mcp = FastMCP("smart_finance_server")
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15"
]
HEADERS = {"User-Agent": random.choice(_USER_AGENTS)}

@mcp.tool()
async def crawl_etnews_articles(keyword: str, pages: int = 1) -> List[Dict[str, str]]:
    """
    根據關鍵字爬取 ETtoday 搜尋結果，並回傳每篇的標題、連結、內文與日期
    """
    articles = []
    async with httpx.AsyncClient(http2=True, headers=HEADERS, follow_redirects=True) as sess:
        for page in range(1, pages + 1):
            url = f"https://www.ettoday.net/news_search/doSearch.php?keywords={keyword}&page={page}"
            try:
                res = await sess.get(url, timeout=15.0)
                res.raise_for_status()
            except Exception as e:
                print(f"搜尋頁面獲取失敗: {e}")
                continue

            soup = BeautifulSoup(res.text, "lxml")

            for box in soup.select(".box_2"):
                title_tag = box.select_one("h2 a")
                date_tag = box.select_one("p.detail span.date")
                if not title_tag or not date_tag:
                    continue

                title = title_tag.text.strip()
                link = title_tag["href"]
                date_match = re.search(r"\d{4}-\d{2}-\d{2}", date_tag.text)
                news_date = date_match.group(0) if date_match else ""

                try:
                    art_res = await sess.get(link, timeout=20.0)
                    art_res.raise_for_status()
                    art_soup = BeautifulSoup(art_res.text, "lxml")
                    main = art_soup.select_one("#main-content") or art_soup.select_one(".story")
                    content = main.get_text("\n", strip=True) if main else "(無法取得內文)"
                except Exception as e:
                    content = f"(抓取失敗: {e})"

                articles.append({
                    "title": title,
                    "link": link,
                    "date": news_date,
                    "content": content,
                    "keyword": keyword
                })
    return articles