"""Finance News Summary Tool for FastMCP

Searches ETtoday Finance news, bundles all retrieved articles into a
single corpus, and asks GPT‑4o to read *all* of them together to answer
the user’s question.

Install with:
    mcp install finance_news_tool.py
Then call:
    await etnews_finance_summary("鴻海配息會衝擊股價嗎？", pages=1, limit=5)
"""

from __future__ import annotations
import traceback
import os
import random
import re
import json
from typing import List, Dict
from datetime import datetime
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastmcp import FastMCP
from openai import AsyncOpenAI
import sys


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------
load_dotenv()
mcp = FastMCP("smart_finance_news")
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15",
]
HEADERS = {"User-Agent": random.choice(_USER_AGENTS)}

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def parse_question(question: str) -> dict:
    """
    將使用者輸入的財經問題轉換為結構化的 JSON 格式
    """
    prompt = f"""
你是一個財經語意分析助手，請將下列問題解析為結構化的 JSON 格式。若有缺漏資訊，請合理推測或補齊。

問題：
「{question}」

請輸出以下欄位（直接以 JSON 格式回傳）：
- company：公司名稱（若無則為空字串）
- stock_id：股票代號（必須是數字）
- topic：問題主題（如財報、營收、法說會、關稅等）

stock_id 與 company 為必填。
請**只輸出純 JSON格式**，不要加註解，不要加反引號。
"""
    chat = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    result = chat.choices[0].message.content.strip()
    try:
        return json.loads(result)
    except Exception as e:
        return {"error": f"解析失敗：{e}", "raw": result}


async def _crawl_ettoday(keyword: str, pages: int) -> List[Dict[str, str]]:
    """
    根據關鍵字與頁數爬取 ETtoday 搜尋結果，並回傳每篇的標題、連結、內文與日期
    """
    articles = []

    async with httpx.AsyncClient(http2=True, headers=HEADERS, follow_redirects=True) as sess:
        for page in range(1, pages + 1):
            url = f"https://www.ettoday.net/news_search/doSearch.php?keywords={keyword}&page={page}"
            try:
                res = await sess.get(url, timeout=15.0)
                res.raise_for_status()
            except Exception:
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


async def _gpt_answer(question: str, articles: List[Dict[str, str]]) -> str:
    """
    整合多篇文章並請 GPT-4o 回答問題
    """
    docs = [
        f"【第 {i+1} 篇】\n標題：{a['title']}\n連結：{a['link']}\n內文：\n{a['content'][:3000]}\n"
        for i, a in enumerate(articles)
    ]
    corpus = "\n".join(docs)

    prompt = (
        f"你是一位專業的財經分析助手。以下提供 {len(articles)} 篇 ETtoday 新聞，請先整合重點，再根據使用者提問給出專業、精簡的回覆。\n\n"
        f"【使用者問題】\n{question}\n\n{corpus}\n\n"
        "請輸出格式：\n1️⃣ 綜合新聞摘要（重點條列）\n2️⃣ 針對使用者問題的回答（250 字內）"
    )

    chat = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return chat.choices[0].message.content.strip()


@mcp.tool()
async def etnews_finance_summary(question: str, pages: int = 1, limit: int = 5) -> dict:
    """
    根據問題爬取 ETtoday 新聞，整合文章後讓 GPT 給出摘要與回答
    """
    parsed = await parse_question(question)
    if "error" in parsed:
        return {
            "status": "error",
            "message": f"問題解析失敗：{parsed['error']}",
            "raw": parsed.get("raw", "")
        }


    keyword = f"{parsed.get('company', '')}{parsed.get('topic', '')}".strip()
    if not keyword:
        return "⚠️ 無法組出有效關鍵字"

    articles = await _crawl_ettoday(keyword, pages)
    if not articles:
        return "⚠️ 找不到符合條件的新聞。請換個問題試試。"

    return await _gpt_answer(question, articles[:limit])

def handle_exception(exc_type, exc_value, exc_traceback):
    print("❌ MCP Server 發生未處理例外：", file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
    sys.exit(1)

sys.excepthook = handle_exception

if __name__ == "__main__":
    sys.stdout = open(os.devnull, 'w') 
    print("✅ Finance News MCP 工具正在啟動...", file=sys.stderr)
    mcp.run()