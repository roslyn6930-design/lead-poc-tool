import streamlit as st
import pandas as pd
from fuzzywuzzy import process

# ========== 頁面設定 ==========
st.set_page_config(page_title="商機挖掘工具", layout="wide")
st.title("商機挖掘工具｜POC測試版")

# ========== 側邊欄 ==========
with st.sidebar:
    st.header("參數設定")
    threshold = st.slider("模糊比對閾值", min_value=0, max_value=100, value=80, help="數值越高，名稱比對越嚴格")
    st.divider()
    st.info("📌 本版本：純模糊比對，暫不呼叫Tavily、Gemini API")

# ========== 主頁面 ==========
tab1, tab2 = st.tabs(["CRM資料上傳與比對", "產業搜尋測試"])

with tab1:
    st.subheader("1. 上傳 CRM 客戶清單 (CSV)")
    uploaded_file = st.file_uploader("選擇 fake_crm.csv", type="csv")

    if uploaded_file is not None:
        df_crm = pd.read_csv(uploaded_file)
        st.success("✅ CSV 上傳成功！")
        st.write("📋 CSV 內所有欄位名稱：")
        st.write(df_crm.columns.tolist()) # 印出所有欄位，方便確認

        st.dataframe(df_crm, use_container_width=True)

        st.subheader("2. 輸入要比對的公司名稱")
        target_name = st.text_input("公司名稱：", placeholder="例如：台北防偽科技股份有限公司")

        if target_name:
            # 自動找對應欄位，這裡假設你的欄位是「公司名稱」，如果不是，看上面印出來的欄位名去改
            col_name = "公司名稱"
            if col_name not in df_crm.columns:
                st.error(f"❌ 找不到欄位：{col_name}，請檢查上面列出的CSV欄位！")
            else:
                company_list = df_crm[col_name].tolist()
                match_result = process.extractOne(target_name, company_list, score_cutoff=threshold)

                st.subheader("3. 比對結果")
                if match_result:
                    match_name, score = match_result
                    st.write(f"匹配公司：**{match_name}**")
                    st.write(f"匹配分數：{score}")
                    st.dataframe(df_crm[df_crm[col_name] == match_name], use_container_width=True)
                else:
                    st.warning("❌ 找不到符合閾值的公司")

with tab2:
    st.subheader("產業搜尋（模擬模式）")
    industry_options = ["防偽溯源", "包裝印刷", "品牌授權", "進出口貿易", "食品製造"]
    selected_industry = st.selectbox("選擇產業", industry_options)
    st.write(f"你選擇的產業：{selected_industry}")
    st.info("目前為模擬模式，後續接入Tavily API才會真的上網搜尋商機")
