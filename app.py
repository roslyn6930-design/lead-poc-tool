import streamlit as st
import pandas as pd
from fuzzywuzzy import process
import requests
import json

st.set_page_config(page_title="商機挖掘工具｜客戶快速檢查版", layout="wide")
st.title("🛡️ 商機挖掘工具｜輸入客戶快速檢查")

# ========= 讀取 Secrets =========
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY", "")
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
HAS_API = bool(TAVILY_API_KEY and GROQ_API_KEY)

# ========= Session 狀態 =========
if "df_crm" not in st.session_state:
    st.session_state.df_crm = None

# ========= 函數區 =========
def crm_fuzzy_check(company_input, df_crm, threshold=80):
    """CRM模糊比對，內部使用，介面不顯示分數"""
    col = "公司名稱"
    name_list = df_crm[col].astype(str).tolist()
    res = process.extractOne(company_input, name_list, score_cutoff=threshold)
    if res:
        match_name, _ = res
        row = df_crm[df_crm[col]==match_name].iloc[0].to_dict()
        return True, row
    return False, None


def tavily_company_search(company_name):
    """針對單一公司搜尋假貨、竄貨、低價、社群新聞"""
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
    """Groq LLM摘要，取代Gemini，解決地區404攔截"""
    prompt = f"""
你是品牌防偽銷售助理，針對【{company_name}】整理網路搜尋結果。
輸出JSON物件，欄位：
- risk_level：高 / 中 / 低 （高：有假貨/竄貨/亂價公開事件；中：有通路風險但無明確事件；低：無相關負面資訊）
- summary：繁體中文，150字以內，整理觀察重點，消費者抱怨、仿冒、竄貨、低價亂價等資訊
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


# ========= UI介面 =========
with st.sidebar:
    st.header("1.上傳CRM客戶CSV")
    upload_file = st.file_uploader("必須有欄位：公司名稱", type="csv")
    fuzzy_thres = st.slider("模糊比對門檻(內部邏輯)", min_value=60, max_value=95, value=80)
    st.divider()
    st.info(f"網路查詢功能：{'✅已啟用' if HAS_API else '❌未設定API金鑰(僅CRM比對可用)'}")

    if upload_file is not None:
        try:
            df = pd.read_csv(upload_file)
            st.session_state.df_crm = df
            st.success(f"CRM載入成功，共{len(df)}筆")
            st.caption(f"欄位：{df.columns.tolist()}")
        except Exception as e:
            st.error(f"讀取CSV失敗：{e}")


st.subheader("2.輸入欲開發檢查的客戶公司名")
input_company = st.text_input("公司名稱", placeholder="例如：晶亮美妝生技股份有限公司")
run_btn = st.button("🔎 開始檢查（CRM比對 + 網路輔助查詢）")

if run_btn:
    if st.session_state.df_crm is None:
        st.warning("請先上傳CRM的CSV檔案！")
        st.stop()
    if not input_company.strip():
        st.warning("請輸入公司名稱")
        st.stop()

    tab_crm, tab_web = st.tabs(["📋 CRM客戶比對結果","🌐 網路輔助資訊(假貨/竄貨/新聞)"])

    # -------- CRM比對 --------
    with tab_crm:
        exist, info_row = crm_fuzzy_check(input_company, st.session_state.df_crm, threshold=fuzzy_thres)
        if exist:
            st.success(f"✅ 該客戶已存在CRM系統內")
            st.dataframe(pd.DataFrame([info_row]), use_container_width=True)
        else:
            st.info(f"🆕 CRM查無此客戶，視為潛在新開發客戶")

    # -------- 網路查詢（有金鑰才執行） --------
    with tab_web:
        if not HAS_API:
            st.info("⚠️ Tavily / Groq API金鑰尚未設定，跳過網路查詢；請至Streamlit Secrets填入金鑰")
        else:
            try:
                with st.spinner("正在上網搜尋假貨、竄貨、社群與新聞資訊..."):
                    search_result = tavily_company_search(input_company)
                with st.spinner("LLM整理風險摘要..."):
                    news_json = llm_summarize_news(input_company, search_result)

                st.markdown(f"**風險等級：{news_json['risk_level']}**")
                st.markdown(f"**摘要：** {news_json['summary']}")
                st.subheader("📎 資訊來源清單")
                for s in news_json["source_list"]:
                    st.markdown(f"- [{s['title']}]({s['url']})")

            except Exception as err:
                st.error(f"網路查詢發生錯誤：{str(err)}")
                st.caption("可能原因：金鑰錯誤、配額用完、網路連線問題；CRM比對功能不受影響。")


st.divider()
st.caption("說明：網路資訊僅供業務參考，請務必人工核實內容真實性。\n⚠️ 提醒：本工具CRM資料存於瀏覽器暫存，重新整理頁面資料會消失，每次使用請重新上傳最新CRM CSV。")
