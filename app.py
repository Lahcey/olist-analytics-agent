from pathlib import Path

import pandas as pd
import streamlit as st

from ask_database import execute_sql, generate_sql, is_refusal, validate_sql


st.set_page_config(page_title="Olist 数据查询", page_icon="📊")
st.title("📊 Olist 电商数据查询")
st.caption("使用自然语言查询公开电商数据；请核对 SQL 和指标口径。")

guide_path = Path(__file__).with_name("database_guide.txt")
if not guide_path.exists():
    st.error("找不到 database_guide.txt，请确认它与 app.py 位于同一文件夹。")
    st.stop()

with st.form("generate_form"):
    api_key = st.text_input("百炼 API Key", type="password")
    question = st.text_area(
        "请输入数据问题",
        placeholder="例如：2017 年 11 月销售额最高的前三个商品品类是什么？",
    )
    generate_clicked = st.form_submit_button("生成 SQL")

if generate_clicked:
    # 每次新问题都先清除旧查询，防止误执行上一个问题的 SQL。
    st.session_state.pop("validated_sql", None)
    st.session_state.pop("validated_question", None)
    if not api_key.strip() or not question.strip():
        st.warning("请输入 API Key 和问题。")
    else:
        try:
            guide = guide_path.read_text(encoding="utf-8-sig")
            with st.spinner("正在生成 SQL……"):
                generated = generate_sql(question.strip(), guide, api_key.strip()).strip()
            if is_refusal(generated):
                st.info("现有数据或查询能力不足，无法回答这个问题。")
            else:
                validated = validate_sql(generated)
                st.session_state["validated_sql"] = validated
                st.session_state["validated_question"] = question.strip()
        except Exception as error:
            st.error(f"生成或检查失败：{type(error).__name__}。请检查模型服务、问题和项目配置。")

if "validated_sql" in st.session_state:
    st.subheader("待查询的问题")
    st.write(st.session_state["validated_question"])
    st.subheader("生成的 SQL")
    st.code(st.session_state["validated_sql"], language="sql")
    st.caption("请检查查询范围和指标口径，再执行查询。")

    with st.form("execute_form"):
        db_password = st.text_input("olist_reader 数据库密码", type="password")
        execute_clicked = st.form_submit_button("执行只读查询")

    if execute_clicked:
        if not db_password:
            st.warning("请输入数据库密码。")
        else:
            try:
                with st.spinner("正在查询数据库……"):
                    columns, rows = execute_sql(st.session_state["validated_sql"], db_password)
                st.subheader("查询结果")
                if rows:
                    st.dataframe(pd.DataFrame(rows[:100], columns=columns), hide_index=True)
                    if len(rows) > 100:
                        st.caption("结果超过 100 行，仅显示前 100 行。")
                else:
                    st.info("没有查询结果。")
            except Exception as error:
                st.error(f"数据库查询失败：{type(error).__name__}。请检查数据库服务和密码。")
