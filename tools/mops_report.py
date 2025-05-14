# tools/mops_report.py
from fastmcp import FastMCP
import os
import json
import traceback
import pandas as pd
import time
from io import StringIO
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

mcp = FastMCP("smart_finance_server")

@mcp.tool()
async def fetch_mops_report(stock_ids: list[str], years: list[int], seasons: list[int]) -> dict:
    """
    使用 Selenium 從 MOPS 擷取指定公司指定年份與季度的財報表格
    """
    stock_ids = [str(sid) for sid in stock_ids]
    years = [int(y) for y in years]
    seasons = [int(s) for s in seasons]
    all_results = {}

    for stock_id in stock_ids:
        for year in years:
            for season in seasons:
                key = f"{stock_id}_{year}Q{season}"
                filename = f"{key}.json"
                if os.path.exists(filename):
                    with open(filename, "r", encoding="utf-8") as f:
                        all_results[key] = json.load(f)
                    continue

                url = f"https://mopsov.twse.com.tw/server-java/t164sb01?step=3&CO_ID={stock_id}&SYEAR={year}&SSEASON={season}&REPORT_ID=C"
                options = Options()
                options.add_argument("--headless")
                options.add_argument("--disable-gpu")
                options.add_argument("window-size=1920,1080")
                options.add_argument("user-agent=Mozilla/5.0")
                driver = webdriver.Chrome(options=options)
                driver.get(url)

                try:
                    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
                    time.sleep(2)  # 添加延遲確保內容完全載入
                    soup = BeautifulSoup(driver.page_source, "html.parser")
                    tables = soup.find_all("table")

                    all_tables = []
                    for idx, table in enumerate(tables[:5]):
                        try:
                            html_str = str(table)
                            df = pd.read_html(StringIO(html_str))[0]
                            if isinstance(df.columns, pd.MultiIndex):
                                df.columns = ['_'.join([str(i) for i in col if pd.notna(i)]) for col in df.columns]
                            df.dropna(how='all', inplace=True)
                            table_dict = df.to_dict(orient="records")
                            all_tables.append({
                                "table_index": idx,
                                "preview": df.head(3).to_string(index=False),
                                "data": table_dict
                            })
                        except Exception as e:
                            print(f"處理表格 {idx} 時發生錯誤: {e}")
                            continue
                    all_results[key] = all_tables
                    with open(filename, "w", encoding="utf-8") as f:
                        json.dump(all_tables, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"擷取 {key} 的財報資料時發生錯誤: {e}")
                    all_results[key] = None
                finally:
                    driver.quit()
    return all_results