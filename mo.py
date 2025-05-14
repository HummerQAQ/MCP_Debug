# mo.py
from fastmcp import FastMCP
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
import json
import sys
import traceback
from tools.mops_report import fetch_mops_report
from tools.news_summary import crawl_etnews_articles

# 載入環境變數
load_dotenv()
# 初始化 FastMCP 服務器
mcp = FastMCP("smart_finance_server")
# 初始化 OpenAI 客戶端
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
    try:
        chat = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        result = chat.choices[0].message.content.strip()
        return json.loads(result)
    except json.JSONDecodeError as e:
        return {"error": f"解析失敗：無法解析 JSON: {e}", "raw": result}
    except Exception as e:
        return {"error": f"解析失敗：{e}"}

@mcp.tool()
async def analyze_financial_data(question: str, stock_id: str = "", company: str = "", topic: str = "", pages: int = 1) -> str:
    """
    整合財報與新聞資訊，針對使用者問題進行綜合分析
    """
    # 如果未提供股票代號和公司名稱，先解析問題
    if not stock_id or not company:
        parsed = await parse_question(question)
        if "error" in parsed:
            return f"⚠️ 問題解析失敗：{parsed['error']}"
        
        stock_id = parsed.get("stock_id", "")
        company = parsed.get("company", "")
        topic = parsed.get("topic", "")
    
    # 收集新聞文章
    keyword = f"{company}{topic}".strip()
    if keyword:
        news = await crawl_etnews_articles(keyword, pages)
    else:
        news = []
    
    # 如果有股票代號，收集財報資料
    if stock_id:
        try:
            # 預設查詢最近的年度和季度
            reports = await fetch_mops_report([stock_id], [2024, 2023], [1, 4])
        except Exception as e:
            reports = {"error": f"財報抓取失敗：{e}"}
    else:
        reports = {}
    
    # 使用 GPT 分析資料
    news_summary = "\n---\n".join([f"標題：{a['title']}\n日期：{a['date']}\n摘要：{a['content'][:300]}..." for a in news[:3]]) if news else "未找到相關新聞"
    
    prompt = f"""
我正在分析關於 {company} (股票代號: {stock_id}) 的財經資訊，請根據以下資料回答問題：

【問題】
{question}

【新聞資料】
找到 {len(news)} 篇相關新聞:
{news_summary}

【財報資料】
{json.dumps(reports, ensure_ascii=False, indent=2)[:2000]}...

請針對問題提供簡短但有深度的分析，提供具體數據支持，並給出風險評估與建議。語氣專業但易懂。
"""
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"❌ 分析失敗：{e}"

@mcp.tool()
async def etnews_finance_summary(question: str, pages: int = 1, limit: int = 5) -> str:
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

    articles = await crawl_etnews_articles(keyword, pages)
    if not articles:
        return "⚠️ 找不到符合條件的新聞。請換個問題試試。"

    docs = [
        f"【第 {i+1} 篇】\n標題：{a['title']}\n連結：{a['link']}\n內文：\n{a['content'][:3000]}\n"
        for i, a in enumerate(articles[:limit])
    ]
    corpus = "\n".join(docs)

    prompt = (
        f"你是一位專業的財經分析助手。以下提供 {len(articles[:limit])} 篇 ETtoday 新聞，請先整合重點，再根據使用者提問給出專業、精簡的回覆。\n\n"
        f"【使用者問題】\n{question}\n\n{corpus}\n\n"
        "請輸出格式：\n1️⃣ 綜合新聞摘要（重點條列）\n2️⃣ 針對使用者問題的回答（250 字內）"
    )

    try:
        chat = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return chat.choices[0].message.content.strip()
    except Exception as e:
        return f"❌ GPT 分析失敗：{e}"

def handle_exception(exc_type, exc_value, exc_traceback):
    print("❌ MCP Server 發生未處理例外：", file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
    sys.exit(1)

sys.excepthook = handle_exception

if __name__ == "__main__":
    print("✅ Smart Finance MCP 工具正在啟動...", file=sys.stderr)
    mcp.run()