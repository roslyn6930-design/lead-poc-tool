import streamlit as st
import pandas as pd
from fuzzywuzzy import process
import requests
import json

st.set_page_config(page_title="品牌防護商機挖掘工具", layout="wide")

# ========= 讀取Secret內的API金鑰 =========
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY", "")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# ========= Session 初始化 =========
if "crm_df" not in st.session_state:
    st.session_state.crm_df = None
if "leads_result" not in st.session_state:
    st.session_state.leads_result = None

# ========= Tavily搜尋函數 =========
def tavily_search(query: str):
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": 8
    }
    resp = requests.post(url, json=payload)
    return resp.json()

# ========= Gemini LLM解析函數 =========
def parse_leads_with_llm(search_result):
    prompt = f"""
你是品牌防偽溯源銷售分析師，根據下面網路搜尋結果，輸出JSON陣列。
每一筆潛在商機物件欄位：
- company_name：公司完整名稱
- pain_point：簡述痛點，例如假貨、竄貨、多通路銷售風險
- opportunity_level：A / B / C
  A：近期有假貨、仿冒、竄貨公開事件，高優先拜訪
  B：多經銷/電商通路，有潛在風險，中優先
  C：產業相關但無明顯痛點，低優先
- cold_opening：100字以內，台灣商務陌生拜訪開場白
- source_url：對應資訊來源網址

只回傳JSON，不要額外說明文字。
搜尋資料：
{json.dumps(search_result, ensure_ascii=False)}
"""
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    llm_payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    r = requests.post(gemini_url, json=llm_payload)
    data = r.json()
    text_out = data["candidates"][0]["content"]["parts"][0]["text"]
    # 清洗markdown ```json 標記
    text_out = text_out.replace("```json","").replace("```","").strip()
    return json.loads(text_out)

# ========= CRM模糊比對函數 =========
def crm_fuzzy_match(lead_company, crm_company_list, threshold=80):
    match, score = process.extractOne(lead_company, crm_company_list) if crm_company_list else (None,0)
    if score >= threshold:
        return True, match, score
    return False, None, score

# ========= 頁面UI =========
st.title("🛡️ 品牌防護｜商機挖掘工具 V1.1")
st.markdown("循序升級版：Tavily搜尋 + LLM商機評分 + CRM模糊比對")

with st.sidebar:
    st.header("1.上傳CRM客戶清單CSV")
    crm_upload = st.file_uploader("CSV需包含欄位 company_name", type="csv")
    if crm_upload is not None:
        st.session_state.crm_df = pd.read_csv(crm_upload)
        st.success(f"CRM已載入，共 {len(st.session_state.crm_df)} 筆")
        crm_name_list = st.session_state.crm_df["company_name"].astype(str).tolist()
    else:
        crm_name_list = []

    st.header("2.搜尋設定")
    search_keyword = st.text_area("搜尋關鍵字", value="保養品 食品 仿冒 竄貨 品牌通路")
    hide_exist = st.checkbox("只顯示全新客戶", value=False)
    fuzzy_threshold = st.slider("模糊比對門檻", min_value=60, max_value=95, value=80)

    run_btn = st.button("🔍 執行商機搜尋")

# ========= 執行搜尋流程 =========
if run_btn:
    if not TAVILY_API_KEY or not GEMINI_API_KEY:
        st.error("請至Streamlit Secrets設定 TAVILY_API_KEY、GEMINI_API_KEY")
    else:
        with st.spinner("Tavily上網搜尋中..."):
            search_res = tavily_search(search_keyword)
        with st.spinner("LLM解析商機、產生拜訪文案..."):
            raw_leads = parse_leads_with_llm(search_res)

        result_rows = []
        for lead in raw_leads:
            is_exist, match_name, match_score = crm_fuzzy_match(lead["company_name"], crm_name_list, threshold=fuzzy_threshold)
            row = {
                "公司名": lead["company_name"],
                "商機等級": lead["opportunity_level"],
                "痛點摘要": lead["pain_point"],
                "陌生拜訪開場白": lead["cold_opening"],
                "來源網址": lead["source_url"],
                "是否CRM既有客戶": is_exist,
                "匹配名稱": match_name if match_name else "",
                "匹配分數": match_score
            }
            result_rows.append(row)

        df_result = pd.DataFrame(result_rows)
        # 過濾已開發客戶
        if hide_exist:
            df_result = df_result[df_result["是否CRM既有客戶"]==False]
        st.session_state.leads_result = df_result

# ========= 呈現結果 =========
if st.session_state.leads_result is not None:
    df_show = st.session_state.leads_result
    st.subheader("📋 潛在商機清單")
    st.dataframe(df_show, use_container_width=True)
    csv_data = df_show.to_csv(index=False, encoding="utf‑8‑sig")
    st.download_button(label="📥 下載結果CSV", data=csv_data, file_name="商機清單.csv", mime="text/csv")

st.divider()
st.info("第一階段版本：尚未接入Dcard/PTT社群抓取；下一階段再加入社群輿情模組。")
