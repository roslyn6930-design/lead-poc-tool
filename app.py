import streamlit as st
import pandas as pd
from fuzzywuzzy import process

st.set_page_config(
    page_title="防偽溯源｜銷售商機挖掘工具",
    layout="wide"
)

if "crm_data" not in st.session_state:
    st.session_state["crm_data"] = None
if "result_data" not in st.session_state:
    st.session_state["result_data"] = None

mock_leads = [
    {"company_name":"統一企業股份有限公司","business_reason":"蝦皮出現低價仿冒飲品討論","source":"社群討論"},
    {"company_name":"永信藥品工業","business_reason":"Dcard網友抱怨買到來源不明藥品","source":"社群討論"},
    {"company_name":"麗寶生技股份有限公司","business_reason":"PTT開箱文懷疑保養品仿冒","source":"社群討論"},
    {"company_name":"星光美妆有限公司","business_reason":"Threads大量平行輸入低價商品，竄貨風險","source":"社群討論"},
    {"company_name":"海嵐食品","business_reason":"購物社群假貨檢舉，缺少溯源機制","source":"社群討論"},
    {"company_name":"星耀生技股份有限公司","business_reason":"蝦皮賣場大量超低價仿品","source":"社群討論"},
]

with st.sidebar:
    st.header("設定")
    match_threshold = st.slider("模糊比對閾值（越高越嚴格）", min_value=60, max_value=100, value=80)
    hide_exist_customer = st.checkbox("只顯示全新客戶", value=False)

    st.divider()
    st.subheader("上傳CRM客戶清單 CSV")
    upload_crm = st.file_uploader("CSV欄位必須包含 company_name", type="csv")
    if upload_crm is not None:
        st.session_state["crm_data"] = pd.read_csv(upload_crm)
        st.success(f"CRM載入成功，共 {len(st.session_state['crm_data'])} 筆客戶")

st.title("🛡️ 品牌防護｜商機挖掘工具 POC")
st.markdown("POC版本：測試CRM模糊比對與客戶篩選，**無需API**")

st.subheader("🔍 載入模擬潛在商機")
run_btn = st.button("載入模擬潛在客戶清單")

if run_btn:
    df_leads = pd.DataFrame(mock_leads)
    crm_df = st.session_state["crm_data"]
    output = []

    if crm_df is not None:
        crm_company_list = crm_df["company_name"].tolist()
        for _, lead in df_leads.iterrows():
            company = lead["company_name"]
            match_name, score = process.extractOne(company, crm_company_list)
            if score >= match_threshold:
                crm_row = crm_df[crm_df["company_name"] == match_name].iloc[0]
                status = f"✅ CRM已存在｜匹配:{match_name} 分數:{score}"
                contact = crm_row.get("contact_person","")
                crm_status = crm_row.get("status","")
            else:
                status = "❌ 全新潛在客戶"
                contact = ""
                crm_status = ""

            new_row = lead.to_dict()
            new_row["crm_status"] = status
            new_row["crm_contact"] = contact
            new_row["crm_develop_status"] = crm_status
            output.append(new_row)
    else:
        for _, lead in df_leads.iterrows():
            tmp = lead.to_dict()
            tmp["crm_status"] = "❌ 全新潛在客戶（尚未上傳CRM）"
            tmp["crm_contact"] = ""
            tmp["crm_develop_status"] = ""
            output.append(tmp)

    result_df = pd.DataFrame(output)

    if hide_exist_customer:
        result_df = result_df[result_df["crm_status"].str.startswith("❌")].copy()

    st.session_state["result_data"] = result_df

if st.session_state["result_data"] is not None:
    st.subheader("📋 商機結果清單")
    st.dataframe(st.session_state["result_data"], use_container_width=True)

    csv_export = st.session_state["result_data"].to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        label="📥 下載結果 CSV",
        data=csv_export,
        file_name="商機挖掘結果.csv",
        mime="text/csv"
    )
