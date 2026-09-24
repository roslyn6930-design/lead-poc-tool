# ========= Gemini LLM解析函數(已修復錯誤處理) =========
def parse_leads_with_llm(search_result):
    prompt = f"""
你是品牌防偽溯源銷售分析師，根據下面網路搜尋結果，輸出JSON陣列。
每一筆潛在商機物件欄位：
- company_name：公司完整名稱
- pain_point：簡述痛點，例如假貨、竄貨、多通路銷售風險
- opportunity_level：A / B / C
  A：近期公開出現假貨、竄貨，高優先拜訪
  B：多經銷/電商通路，有潛在風險，中優先
  C：產業相關但無明顯痛點，低優先
- cold_opening：100字以內，台灣商務陌生拜訪開場白
- source_url：對應資訊來源網址

只回傳JSON，不要額外說明文字，不要markdown標記。
搜尋資料：
{json.dumps(search_result, ensure_ascii=False)}
"""
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    llm_payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    r = requests.post(gemini_url, json=llm_payload)
    data = r.json()

    # 增加錯誤判斷，解決KeyError崩潰
    if "error" in data:
        raise Exception(f"Gemini API錯誤：{data['error']['message']}")
    if "candidates" not in data or len(data["candidates"]) == 0:
        raise Exception("Gemini沒有產生回應，可能是金鑰錯誤、額度耗盡或是地區限制")

    text_out = data["candidates"][0]["content"]["parts"][0]["text"]
    # 清洗markdown ```json 標記
    text_out = text_out.replace("```json","").replace("```","").strip()
    try:
        return json.loads(text_out)
    except json.JSONDecodeError:
        raise Exception(f"LLM輸出無法解析JSON，原始輸出：{text_out}")
