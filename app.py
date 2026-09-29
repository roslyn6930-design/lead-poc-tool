import streamlit as st

st.title("商機挖掘工具 - 測試頁")
st.write("如果看到這行，代表 Streamlit 正常啟動！")

threshold = st.slider("模糊比對閾值", min_value=0, max_value=100, value=80)
st.write(f"目前閾值設定：{threshold}")
