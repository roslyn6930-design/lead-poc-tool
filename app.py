import streamlit as st
import pandas as pd
from fuzzywuzzy import process
import requests
import json

st.set_page_config(page_title="商機挖掘工具 V2.0", layout="wide")
st.title("🛡️ 商機挖掘工具 V2.0｜客戶檢查 + 批量商機挖掘")

# ========= Secrets讀取 =========
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY", "")
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
HAS_API = bool(TAVILY_API_KEY and GROQ_API_KEY)

# ========= Session狀態初始化 =========
def init_session():
    if "df_crm" not in st.session_state:
        st.session_state.df_crm = None
    if "df_blacklist" not in st.session_state:
        st.session_state.df_blacklist = None
    if "query_triggered" not in st.session_state:
        st.session_state.query_triggered = False
    if "result_data" not in st.session_state:
        st.session_state.result_data = None
    if "batch_result" not in st.session_state:
        st.session_state.batch_result = []
    if "error_msg" not in st.session_state:
        st.session_state.error_msg = None

init_session()

# ========= 共用函數 =========
def crm_fuzzy_check(company_input, df_crm, threshold=80):
    col_name = "公司名稱"
    name_list = df_crm[col_name].astype(str).tolist()
    res = process.extractOne(company_input, name_list, score_cutoff=threshold)
    if not res:
        return {"status":"new_prospect", "match_row":None}
    match_name, _ = res
    row = df_crm[df_crm[col_name]==match_name].iloc[0].to_dict()
    cust_type = str(row.get("客戶類型","")).strip()
    target_tag = str(row.get("目標標籤","")).strip()
    if target_tag and target_tag != "nan":
        return {"status":"existing_customer", "match_row":row}
    else:
        return {"status":"crm_stock_no_tag", "match_row":row}

def is_in_blacklist(company_name, df_blacklist):
    if df_blacklist is None:
        return False
    black_list = df_blacklist["公司名稱"].astype(str).tolist()
    match = process.extractOne(company_name, black_list, score_cutoff=80)
    return match is not None

def tavily_company_search(company_name):
    query = f'"{company_name}" 假貨 OR 仿冒 OR 竄貨 OR 亂價 OR 低價 OR 消費者抱怨 OR Dcard OR PTT OR 新聞'
    payload = {"api_key":TAVILY_API_KEY,"query":query,"search_depth":"basic","max_results":6,"topic":"general"}
    resp = requests.post("https://api.tavily.com/search", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()

def llm_summarize_single(company_name, search_data):
    prompt = f"""
你是品牌防偽銷售助理，針對【{company_name}】整理網路搜尋結果。
輸出JSON物件，欄位：
- risk_level：高 / 中 / 低
- has_potential_demand：true / false
- summary：繁體中文，150字以內，整理重點，仿冒、竄貨、低價亂價、消費者抱怨
- source_list：陣列，每筆包含title、url
只輸出JSON，不要markdown，不要額外文字。
搜尋資料：{json.dumps(search_data, ensure_ascii=False)}
"""
    headers = {"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}
    payload = {"model":"llama-3.1-8b-instant","messages":[{"role":"user","content":prompt}],"temperature":0.3}
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=40)
    r.raise_for_status()
    data = r.json()
    raw = data["choices"][0]["message"]["content"].replace("```json","").replace("```","").strip()
    return json.loads(raw)

def llm_parse_batch(raw_search_result, industry_keyword, max_count):
    prompt = f"""
你是防偽銷售助理，依據網路搜尋，挖掘【{industry_keyword}】產業有假貨、竄貨、價格亂象的企業。
最多輸出{max_count}筆。
JSON陣列每一筆欄位：
company_name：公司完整名稱
business_risk：A / B / C，A=有明顯假貨竄貨事件；B=通路多有潛在風險；C=幾乎無風險
angle：繁體中文，80字以內，業務拜訪切入談資
只輸出JSON陣列，不要markdown，不要解釋。
搜尋資料：{json.dumps(raw_search_result, ensure_ascii=False)}
"""
    headers = {"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}
    payload = {"model":"llama-3.1-8b-instant","messages":[{"role":"user","content":prompt}],"temperature":0.3}
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    raw = data["choices"][0]["message"]["content"].replace("```json","").replace("```","").strip()
    return json.loads(raw)

def run_single_query():
    """單筆查詢 enter觸發"""
    company = st.session_state.get("input_company","")
    st.session_state.error_msg = None
    if st.session_state.df_crm is None:
        st.session_state.error_msg = "請先上傳CRM的CSV檔案！"
        st.session_state.query_triggered = False
        return
    if not company.strip():
        st.session_state.error_msg = "請輸入公司名稱"
        st.session_state.query_triggered = False
        return
    res = crm_fuzzy_check(company, st.session_state.df_crm, threshold=st.session_state.get("fuzzy_thres",80))
    st.session_state.result_data = res
    st.session_state.query_triggered = True

def run_batch(industry_keyword, max_items):
    """批量挖掘主流程"""
    if not HAS_API:
        return [{"error":"API金鑰未設定，無法執行批量挖掘"}]
    if st.session_state.df_crm is None:
        return [{"error":"請先上傳CRM CSV"}]
    batch_query = f"{industry_keyword} 假貨 OR 竄貨 OR 亂價 OR 消費者投訴 OR 品牌新聞"
    payload = {"api_key":TAVILY_API_KEY,"query":batch_query,"search_depth":"basic","max_results":12,"topic":"general"}
    resp = requests.post("https://api.tavily.com/search", json=payload, timeout=40)
    raw_search = resp.json()
    parsed_list = llm_parse_batch(raw_search, industry_keyword, max_items)
    output = []
    for item in parsed_list:
        c_name = item.get("company_name","").strip()
        if not c_name:
            continue
        #黑名單過濾
        if is_in_blacklist(c_name, st.session_state.df_blacklist):
            continue
        crm_res = crm_fuzzy_check(c_name, st.session_state.df_crm)
        # 過濾掉真正有目標標籤的既有客戶
        if crm_res["status"] == "existing_customer":
            continue
        output.append({
            "公司名稱":c_name,
            "CRM狀態":crm_res["status"],
            "商機等級":item.get("business_risk","C"),
            "切入角度":item.get("angle",""),
        })
    return output

# ========= 側邊欄 =========
with st.sidebar:
    st.header("📁 資料上傳區")
    st.info("CRM欄位：公司名稱、客戶類型、目標標籤")
    crm_file = st.file_uploader("上傳CRM csv", type="csv")
    black_file = st.file_uploader("上傳黑名單csv(選填)", type="csv")
    if crm_file:
        try:
            df = pd.read_csv(crm_file)
            st.session_state.df_crm = df
            st.success(f"CRM載入成功，共{len(df)}筆")
        except Exception as e:
            st.error(f"CRM讀取失敗:{e}")
    if black_file:
        try:
            df_b = pd.read_csv(black_file)
            st.session_state.df_blacklist = df_b
            st.success(f"黑名單載入成功，共{len(df_b)}筆")
        except Exception as e:
            st.error(f"黑名單讀取失敗:{e}")

    fuzzy_thres = st.slider("模糊比對門檻(內部邏輯)", min_value=60, max_value=95, value=80, key="fuzzy_thres")
    st.divider()
    st.info(f"網路查詢功能：{'✅已啟用' if HAS_API else '❌未設定API金鑰(僅CRM比對可用)'}")

# ========= 主頁籤切換 =========
tab_single, tab_batch = st.tabs(["🔍單筆客戶快速檢查(Enter查詢)","🚀批量商機挖掘(產生開發名單)"])

# ========= 頁籤1：單筆查詢 =========
with tab_single:
    st.subheader("輸入欲檢查的客戶公司名")
    st.text_input("公司名稱", placeholder="例如：晶亮美妝生技股份有限公司",
                 key="input_company", on_change=run_single_query)
    if st.session_state.error_msg:
        st.warning(st.session_state.error_msg)

    if st.session_state.query_triggered and st.session_state.result_data:
        res = st.session_state.result_data
        status = res["status"]
        info_row = res["match_row"]
        st.divider()
        st.subheader("📋 CRM比對結果")
        if status == "existing_customer":
            st.success("✅ 狀態：【既有目標客戶】已有目標標籤，不建議新開發")
            st.dataframe(pd.DataFrame([info_row]), use_container_width=True)
        elif status == "crm_stock_no_tag":
            st.warning("⚠️ 狀態：【CRM有紀錄｜股票客戶，尚未有目標標籤】可納入開發候選，建議參考網路是否有潛在需求")
            st.dataframe(pd.DataFrame([info_row]), use_container_width=True)
        elif status == "new_prospect":
            st.info("🆕 狀態：【完全不在CRM】全新潛在開發名單")

        st.subheader("🌐 網路輔助資訊(假貨/竄貨/新聞)")
        if not HAS_API:
            st.info("⚠️ Tavily / Groq API金鑰尚未設定，跳過網路查詢")
        else:
            company = st.session_state.input_company
            try:
                with st.spinner("搜尋網路資訊..."):
                    search_res = tavily_company_search(company)
                with st.spinner("LLM整理摘要..."):
                    news_json = llm_summarize_single(company, search_res)
                st.markdown(f"**風險等級：{news_json['risk_level']}**")
                demand_text = "✅ 觀察到潛在需求跡象，適合拜訪開發" if news_json["has_potential_demand"] else "ℹ️ 未觀察明顯潛在需求跡象"
                st.markdown(f"**潛在需求判斷：{demand_text}**")
                st.markdown(f"**摘要：** {news_json['summary']}")
                st.subheader("📎 來源清單")
                for s in news_json["source_list"]:
                    st.markdown(f"- [{s['title']}]({s['url']})")
            except Exception as err:
                st.error(f"網路查詢發生錯誤：{str(err)}")
                st.caption("CRM比對不受影響。")

# ========= 頁籤2：批量挖掘 =========
with tab_batch:
    st.subheader("設定挖掘條件，自動產生潛在開發名單")
    col1, col2 = st.columns(2)
    with col1:
        industry_input = st.text_input("目標產業關鍵字", value="保養品")
    with col2:
        max_output = st.number_input("最大輸出筆數", min_value=3, max_value=15, value=8)

    run_batch_btn = st.button("🚀 開始批量挖掘")
    if run_batch_btn:
        if not HAS_API:
            st.error("需要設定Tavily+Groq API金鑰才能執行批量挖掘")
        elif st.session_state.df_crm is None:
            st.error("請先上傳CRM CSV")
        else:
            with st.spinner("正在批量挖掘商機，請稍候(約2‑3分鐘)..."):
                batch_list = run_batch(industry_input, max_output)
                st.session_state.batch_result = batch_list

    if len(st.session_state.batch_result) > 0:
        df_batch = pd.DataFrame(st.session_state.batch_result)
        st.subheader("挖掘結果(已過濾正式標籤客戶+黑名單)")
        filter_level = st.multiselect("過濾商機等級",["A","B","C"],default=["A","B"])
        df_filter = df_batch[df_batch["商機等級"].isin(filter_level)]
        st.dataframe(df_filter, use_container_width=True)
        csv_data = df_filter.to_csv(index=False, encoding="utf‑8‑sig")
        st.download_button(label="📥 下載結果CSV(可匯入CRM)", data=csv_data, file_name="批量商機挖掘結果.csv", mime="text/csv")

st.divider()
st.caption("""
版本V2.0｜說明：
1. 單筆查詢輸入完公司名按Enter直接執行；
2. CRM規則：股票客戶無目標標籤保留做開發候選，有目標標籤正式客戶會被過濾；
3. 批量挖掘：自動搜尋公開痛點，排除正式客戶與黑名單，可下載CSV做陌生開發；
⚠️所有網路資訊僅供參考，務必人工複核；資料存放瀏覽器暫存，重整頁面會消失，記得匯出CSV保存。
""")
