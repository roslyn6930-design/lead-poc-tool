import streamlit as st
import pandas as pd
from fuzzywuzzy import process
import requests
import json
import re

st.set_page_config(page_title="商機挖掘工具 V2.3｜修復Groq400", layout="wide")
st.title("🛡️ 商機挖掘工具 V2.3｜客戶檢查 + 批量商機挖掘")

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
    if "batch_editable_df" not in st.session_state:
        st.session_state.batch_editable_df = None
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
    query = f'"{company_name}" 假貨 OR 仿冒 OR 竄貨 OR 亂價 OR 低價 OR 消費者抱怨'
    payload = {"api_key":TAVILY_API_KEY,"query":query,"search_depth":"basic","max_results":4,"topic":"general"}
    resp = requests.post("https://api.tavily.com/search", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()

def clean_json_text(text):
    """清理LLM輸出，移除markdown標記、特殊符號，解決400/解析失敗"""
    text = re.sub(r"```(json)?", "", text)
    text = text.replace("\n", "").strip()
    return text

def llm_summarize_single(company_name, search_data):
    prompt = f"""
你是品牌防偽銷售助理，針對【{company_name}】整理網路搜尋結果。
只回傳純JSON，不要任何其他文字。
欄位：risk_level(高/中/低), has_potential_demand(boolean), summary(繁體150字內), source_list[title,url]
搜尋：{json.dumps(search_data, ensure_ascii=False)[:2200]}
"""
    headers = {"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}
    payload = {"model":"llama3-70b-8192","messages":[{"role":"user","content":prompt}],"temperature":0.2}
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=40)
    r.raise_for_status()
    data = r.json()
    raw = clean_json_text(data["choices"][0]["message"]["content"])
    return json.loads(raw)


def llm_parse_batch(raw_search_result, industry_keyword, max_count):
    prompt = f"""
你是防偽銷售助理，挖掘【{industry_keyword}】產業有假貨、竄貨、價格亂象的企業。
最多{max_count}筆，只輸出JSON陣列，不要解釋、不要markdown。
每筆欄位：company_name(完整公司名), business_risk(A/B/C), angle(繁體80字內業務切入談資)
A=明顯假貨竄貨事件；B=通路多有潛在風險；C=幾乎無風險。
搜尋資料：{json.dumps(raw_search_result, ensure_ascii=False)[:2500]}
"""
    headers = {"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}
    payload = {"model":"llama3-70b-8192","messages":[{"role":"user","content":prompt}],"temperature":0.2}
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=60)
        if r.status_code >=400:
            return [{"error":f"Groq API回傳錯誤 status={r.status_code}, detail:{r.text[:400]}"}]
        data = r.json()
        raw = clean_json_text(data["choices"][0]["message"]["content"])
        return json.loads(raw)
    except Exception as e:
        return [{"error":f"LLM解析失敗：{str(e)}"}]


def run_batch(industry_keyword, max_items):
    if not HAS_API:
        return [{"error":"API金鑰未設定，無法執行批量挖掘"}]
    if st.session_state.df_crm is None:
        return [{"error":"請先上傳CRM CSV"}]

    batch_query = f"{industry_keyword} 假貨 OR 竄貨 OR 亂價 OR 消費者投訴"
    payload = {"api_key":TAVILY_API_KEY,"query":batch_query,"search_depth":"basic","max_results":8,"topic":"general"}
    try:
        resp = requests.post("https://api.tavily.com/search", json=payload, timeout=40)
        if resp.status_code >=400:
            return [{"error":f"Tavily搜尋API錯誤 status={resp.status_code}"}]
        raw_search = resp.json()
    except Exception as e:
        return [{"error":f"Tavily網路搜尋失敗：{str(e)}"}]

    parsed_list = llm_parse_batch(raw_search, industry_keyword, max_items)
    if len(parsed_list)>=1 and "error" in parsed_list[0]:
        return parsed_list

    output = []
    for item in parsed_list:
        c_name = item.get("company_name","").strip()
        if not c_name:
            continue
        if is_in_blacklist(c_name, st.session_state.df_blacklist):
            continue
        crm_res = crm_fuzzy_check(c_name, st.session_state.df_crm)
        if crm_res["status"] == "existing_customer":
            continue
        output.append({
            "業務勾選跟進": False,
            "公司名稱":c_name,
            "CRM狀態":crm_res["status"],
            "AI初判商機等級":item.get("business_risk","C"),
            "切入角度":item.get("angle",""),
        })
    return output


def run_single_query():
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
            st.warning("⚠️ 狀態：【CRM有紀錄｜股票客戶，尚未有目標標籤】可納入開發候選")
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

# ========= 頁籤2：批量挖掘 =========
with tab_batch:
    st.subheader("設定挖掘條件，自動產生潛在開發名單")
    st.info("💡 AI初判僅供參考，由業務手動勾選【業務勾選跟進】做為正式開發名單")
    col1, col2 = st.columns(2)
    with col1:
        industry_options = ["保養品", "食品飲料", "生技醫療", "服飾精品", "3C電子", "機械設備", "其他(自行輸入)"]
        selected_industry = st.selectbox("選擇目標產業", industry_options)
        if selected_industry == "其他(自行輸入)":
            industry_input = st.text_input("請輸入產業關鍵字")
        else:
            industry_input = selected_industry
    with col2:
        max_output = st.number_input("最大輸出筆數", min_value=3, max_value=15, value=7)

    run_batch_btn = st.button("🚀 開始批量挖掘")
    if run_batch_btn:
        if not HAS_API:
            st.error("需要設定Tavily+Groq API金鑰才能執行批量挖掘")
        elif st.session_state.df_crm is None:
            st.error("請先上傳CRM CSV")
        elif not industry_input:
            st.error("請選擇或輸入產業關鍵字！")
        else:
            with st.spinner("正在批量挖掘商機，請稍候(約2‑3分鐘)..."):
                batch_list = run_batch(industry_input, max_output)
                st.session_state.batch_result = batch_list
                if len(batch_list)>=1 and "error" in batch_list[0]:
                    st.error(batch_list[0]["error"])
                    st.session_state.batch_editable_df = None
                else:
                    st.session_state.batch_editable_df = pd.DataFrame(batch_list)

    if st.session_state.batch_editable_df is not None:
        df_raw = st.session_state.batch_editable_df
        filter_level = st.multiselect("過濾AI初判商機等級",["A","B","C"],default=["A","B"])
        df_filter = df_raw[df_raw["AI初判商機等級"].isin(filter_level)].copy()

        st.subheader("挖掘結果｜業務可手動勾選跟進欄位")
        edited_df = st.data_editor(
            df_filter,
            column_config={
                "業務勾選跟進": st.column_config.CheckboxColumn(
                    "✅業務勾選跟進",
                    help="業務人工判斷，勾選代表列入後續開發跟進名單",
                    default=False
                )
            },
            disabled=["公司名稱","CRM狀態","AI初判商機等級","切入角度"],
            use_container_width=True,
            hide_index=True
        )

        st.divider()
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            csv_all = edited_df.to_csv(index=False, encoding="utf‑8‑sig")
            st.download_button(
                label="📥下載全部顯示結果(含勾選狀態)",
                data=csv_all,
                file_name="批量商機_全部結果.csv",
                mime="text/csv"
            )
        with col_dl2:
            follow_df = edited_df[edited_df["業務勾選跟進"]==True]
            csv_follow = follow_df.to_csv(index=False, encoding="utf‑8‑sig")
            st.download_button(
                label="📥僅下載【業務勾選跟進】名單",
                data=csv_follow,
                file_name="批量商機_業務確認跟進名單.csv",
                mime="text/csv",
                disabled=len(follow_df)==0
            )
        st.caption(f"已手動勾選跟進筆數：{len(follow_df)} 筆")


st.divider()
st.caption("""
版本V2.3｜Groq容錯優化；AI初判 + 業務人工勾選
⚠️瀏覽器暫存，重整頁面勾選狀態會消失，務必匯CSV保存
""")
