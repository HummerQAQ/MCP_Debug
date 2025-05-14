# server.py
from fastapi import FastAPI
from fastmcp import FastMCP
from openai import AsyncOpenAI
import tools.mops_report
import tools.news_summary
import os
from dotenv import load_dotenv
import json
from datetime import datetime

load_dotenv()
app = FastAPI()
mcp = FastMCP("smart_finance_server")   # <-- 必須有 FastMCP instance
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.get("/")
def root():
    return {"message": "Smart Finance Server + MCP is running"}

@app.get("/analyze")
async def analyze(question: str, pages: int = 1, limit: int = 5):
    # Step 1: 語意分析
    prompt = f"""
你是一個財經語意分析助手，請將下列問題解析為結構化的 JSON 格式。若有缺漏資訊，請合理推測或補齊。

問題：
「{question}」

請輸出以下欄位（直接以 JSON 格式回傳）：
- company：公司名稱（若無則為空字串）
- stock_id：股票代號（必須是數字）
- resourse：mops, news, both
- topic：問題主題（如財報、營收、法說會、關稅等）
- year：年度(2021,2022,...)，若無則填入最近一年
- season：季度(1,2,3,4)，若無則填入最近一季

stock_id, company, resourse 為必填。
請**只輸出純 JSON格式**，不要加註解，不要加反引號。
"""
    chat = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    parsed = json.loads(chat.choices[0].message.content.strip())
    company = parsed.get("company", "")
    stock_id = parsed.get("stock_id", "")
    resourse = parsed.get("resourse", "both").lower()
    topic = parsed.get("topic", "")
    year = parsed.get("year", datetime.now().year)
    season = parsed.get("season", (datetime.now().month - 1) // 3 + 1)

    mops_data, news_data = None, None

    # Step 2: 呼叫 tools
    if resourse in ["mops", "both"]:
        mops_data = await mcp.call("fetch_mops_report", {
            "stock_ids": [stock_id],
            "years": [year],
            "seasons": [season]
        })

    if resourse in ["news", "both"]:
        news_data = await mcp.call("crawl_etnews_articles", {
            "keyword": company + topic,
            "pages": pages
        })

    # Step 3: 統整
    news_text = "\n".join([
        f"【第 {i+1} 篇】\n標題：{a['title']}\n連結：{a['link']}\n內文：\n{a['content'][:3000]}\n"
        for i, a in enumerate(news_data[:limit])
    ]) if news_data else "無"

    combined_text = f"""【公司】{company} ({stock_id})
【主題】{topic}
【來源】{resourse}

【MOPS財報資料】：
{json.dumps(mops_data, ensure_ascii=False, indent=2) if mops_data else "無"}

【新聞全文】：
{news_text}

請根據以上資料，提供針對使用者問題「{question}」的完整且具體回答。
務必條列亮點、風險、投資建議，語氣像專業 podcast 主持人，簡單易懂但專業。"""

    final_response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "你是頂尖的財經分析師，擅長將複雜財經資料整理成通俗易懂的投資建議。"},
            {"role": "user", "content": combined_text}
        ],
        temperature=0.5
    )

    return {
        "question": question,
        "semantic_parse": parsed,
        "mops_data": mops_data,
        "news_data": news_data,
        "final_summary": final_response.choices[0].message.content.strip()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6277)  # MCP port + OpenAI可連接 port
