import streamlit as st
import pandas as pd
from fuzzywuzzy import process
import requests
import json

st.set_page_config(page_title="商機挖掘工具｜客戶快速檢查版", layout="wide")
st.title("🛡️ 商機挖掘工具｜輸入客戶快速檢查")
st.caption("💡 輸入公司名稱後，直接按 Enter 鍵即可查詢")

# ========= 讀取 Secrets =========
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY", "")
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
HAS_API = bool(TAVILY_API_KEY and GROQ_API_KEY)

# ========= Session 狀態 =========
if "df_crm" not in st.session_state:
    st.session_state.df_crm = None
if "query_triggered" not in st.session_state:
    st.session_state.query_triggered = False
if "input_company" not in st.session_state:
    st.session_state.input_company = ""

# ========= 函數區 =========
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
        if cust_type == "股票客戶":
            return {"status":"crm_stock_no_tag", "match_row":row}
        else:
            return {"status":"crm_stock_no_tag", "match_row":row}


def tavily_company_search(company_name):
    query = f'"{company_name}" 假貨 OR 仿冒 OR 竄貨 OR 亂價 OR 低價 OR 消費者抱怨 OR Dcard OR PTT OR 新聞'
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth":"basic",
        "max_results":6,
        "topic":"general"
    }
    resp = requests.post("https://api.tavily.com/search", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def llm_summarize_news(company_name, search_data):
    prompt = f"""
你是品牌防偽銷售助理，針對【{company_name}】整理網路搜尋結果。
輸出JSON物件，欄位：
- risk_level：高 / 中 / 低
- has_potential_demand：true / false，是否出現防偽、竄貨、假貨相關潛在需求跡象
- summary：繁體中文，150字以內，整理觀察重點
- source_list：陣列，每筆包含title、url

只輸出JSON，不要markdown、不要額外說明文字。
搜尋資料：
{json.dumps(search_data, ensure_ascii=False)}
"""
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type":"application/json"}
    payload = {
        "model":"llama-3.1-8b-instant",
        "messages":[{"role":"user","content":prompt}],
        "temperature":0.3
    }
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=40)
    r.raise_for_status()
    data = r.json()
    raw_text = data["choices"][0]["message"]["content"]
    raw_text = raw_text.replace("```json","").replace("```","").strip()
    return json.loads(raw_text)


def run_query(company):
    """執行查詢，存結果到session"""
    if st.session_state.df_crm is None:
        st.session_state.query_triggered = False
        st.session_state.error_msg = "請先上傳CRM的CSV檔案！"
        return
    if not company.strip():
        st.session_state.query_triggered = False
        st.session_state.error_msg = "請輸入公司名稱"
        return

    result = crm_fuzzy_check(company, st.session_state.df_crm, threshold=st.session_state.get("fuzzy_thres",80))
    st.session_state.result_data = result
    st.session_state.query_triggered = True
    st.session_state.error_msg = None


# ========= UI介面 =========
with st.sidebar:
    st.header("1.上傳CRM客戶CSV")
    st.info("CSV必須欄位：公司名稱、客戶類型、目標標籤")
    upload_file = st.file_uploader("上傳CRM csv", type="csv")

    if upload_file is not None:
        try:
            df = pd.read_csv(upload_file)
            st.session_state.df_crm = df
            st.success(f"CRM載入成功，共{len(df)}筆")
            st.caption(f"欄位：{df.columns.tolist()}")
        except Exception as e:
            st.error(f"讀取CSV失敗：{e}")

    fuzzy_thres = st.slider("模糊比對門檻(內部邏輯)", min_value=60, max_value=95, value=80, key="fuzzy_thres")
    st.divider()
    st.info(f"網路查詢功能：{'✅已啟用' if HAS_API else '❌未設定API金鑰(僅CRM比對可用)'}")


st.subheader("2.輸入欲開發檢查的客戶公司名（按Enter即查詢）")
input_company = st.text_input(
    "公司名稱",
    placeholder="例如：晶亮美妝生技股份有限公司",
    key="input_company",
    on_change=run_query,
    args=(st.session_state.input_company,)
)


# ========= 顯示查詢結果 =========
if st.session_state.get("error_msg"):
    st.warning(st.session_state.error_msg)

if st.session_state.get("query_triggered") and st.session_state.get("result_data"):
    result = st.session_state.result_data
    status = result["status"]
    info_row = result["match_row"]

    st.subheader("📋 CRM客戶比對結果")
    if status == "existing_customer":
        st.success("✅ 狀態：【既有目標客戶】已有目標標籤，不建議做新開發")
        st.dataframe(pd.DataFrame([info_row]), use_container_width=True)
    elif status == "crm_stock_no_tag":
        st.warning("⚠️ 狀態：【CRM有紀錄｜股票客戶，尚未有目標標籤】可納入開發候選，建議參考網路是否有潛在需求")
        st.dataframe(pd.DataFrame([info_row]), use_container_width=True)
    elif status == "new_prospect":
        st.info("🆕 狀態：【完全不在CRM】全新潛在開發名單")

    # -------- 網路查詢 --------
    st.subheader("🌐 網路輔助資訊(假貨/竄貨/新聞)")
    if not HAS_API:
        st.info("⚠️ Tavily / Groq API金鑰尚未設定，跳過網路查詢；請至Streamlit Secrets填入金鑰")
    else:
        company = st.session_state.input_company
        try:
            with st.spinner("正在上網搜尋假貨、竄貨、社群與新聞資訊..."):
                search_result = tavily_company_search(company)
            with st.spinner("LLM整理風險摘要，判斷是否具備潛在需求..."):
                news_json = llm_summarize_news(company, search_result)

            st.markdown(f"**風險等級：{news_json['risk_level']}**")
            demand_text = "✅ 判斷：觀察到潛在需求跡象，適合拜訪開發" if news_json["has_potential_demand"] else "ℹ️ 判斷：未觀察到明顯潛在需求跡象"
            st.markdown(f"**潛在需求判斷：{demand_text}**")
            st.markdown(f"**摘要：** {news_json['summary']}")
            st.subheader("📎 資訊來源清單")
            for s in news_json["source_list"]:
                st.markdown(f"- [{s['title']}]({s['url']})")

        except Exception as err:
            st.error(f"網路查詢發生錯誤：{str(err)}")
            st.caption("可能原因：金鑰錯誤、配額用完、網路連線問題；CRM比對功能不受影響。")


st.divider()
st.caption("""說明：
1. 輸入公司名後按 Enter 即自動查詢，不需點擊按鈕。
2. CRM比對規則：股票客戶但無目標標籤 → 視為可開發候選；有目標標籤才視為既有客戶。
⚠️ 提醒：本工具CRM資料存於瀏覽器暫存，重新整理頁面資料會消失，每次使用請重新上傳最新CRM CSV。""")
