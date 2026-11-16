from getpass import getpass
from pathlib import Path

import psycopg
import sqlglot
from openai import OpenAI
from sqlglot import exp


def is_refusal(text):
    """Recognize the exact refusal phrase with optional ending punctuation."""
    return text.strip().rstrip("。.!！?？ \t\r\n") == "无法回答"


def validate_sql(sql_text):
    """检查 SQL 是否符合当前版本允许的查询范围。"""

    statements = [
        statement
        for statement in sqlglot.parse(sql_text, read="postgres")
        if statement is not None
    ]

    if len(statements) != 1:
        raise ValueError("只允许执行一条 SQL。")

    tree = statements[0]

    if not isinstance(tree, exp.Select):
        raise ValueError("当前只允许 SELECT 查询。")

    if tree.args.get("with_"):
        raise ValueError("当前版本暂不支持 WITH 查询。")

    if tree.args.get("into") or tree.args.get("locks"):
        raise ValueError("不允许 SELECT INTO 或锁定语句。")

    if len(list(tree.find_all(exp.Select))) != 1:
        raise ValueError("当前版本暂不支持子查询。")

    if list(tree.find_all(exp.Join)):
        raise ValueError("当前版本暂不支持 JOIN。")

    tables = list(tree.find_all(exp.Table))

    if len(tables) != 1:
        raise ValueError("查询必须且只能使用一个数据表或视图。")

    table = tables[0]

    allowed_tables = {
        "order_analysis",
        "order_item_category_analysis",
        "delivery_review_analysis",
        "monthly_customer_analysis",
    }

    if (
        table.name not in allowed_tables
        or table.db not in ("", "public")
        or table.catalog
    ):
        raise ValueError("查询的表或视图不在允许范围内。")

    # 当前练习只开放常用的聚合函数。
    allowed_functions = {"COUNT", "SUM", "AVG", "MIN", "MAX", "AND", "OR", "EXTRACT"}

    for function in tree.find_all(exp.Func):
        # PostgreSQL DATE 'YYYY-MM-DD' is parsed as a literal-to-DATE cast.
        if (
            isinstance(function, exp.Cast)
            and isinstance(function.this, exp.Literal)
            and function.this.is_string
            and function.args.get("to") is not None
            and function.args["to"].is_type("DATE")
        ):
            continue
        function_name = function.sql_name().upper()

        if function_name not in allowed_functions:
            raise ValueError(
                f"当前版本暂不允许函数：{function_name}"
            )

    # 使用解析后的 PostgreSQL SQL 执行
    return tree.sql(dialect="postgres")


def generate_sql(question, database_guide, api_key):
    """调用百炼模型生成 SQL。"""

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=60.0,
        max_retries=0,
    )

    system_prompt = f"""
你是 PostgreSQL 数据分析助手。

请根据数据库说明，为用户问题生成一条 SQL。

要求：
1. 只能查询数据库说明中允许的视图，每次只使用一个视图。
2. 只使用一条 SELECT，不使用 WITH、子查询和 JOIN。
3. 允许 COUNT、SUM、AVG、MIN、MAX 聚合函数及 EXTRACT 日期提取。
4. 遵守数据库说明中的指标口径。
5. 只输出 SQL，不要输出 Markdown 代码块。
6. 如果现有数据无法回答，只输出：无法回答。
7. 不要编造字段或数据。
8. customer_id 不能识别跨订单的真实用户，不得用它计算复购。单月的真实用户数和月内复购数可按说明查询 monthly_customer_analysis；无法从月度汇总计算跨月去重用户数或跨月复购，如遇此类问题输出：无法回答。

数据库说明：
{database_guide}
"""

    response = client.chat.completions.create(
        model="qwen3.7-flash",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        max_tokens=600,
        extra_body={"enable_thinking": False},
    )

    return response.choices[0].message.content or ""


def execute_sql(sql_text, database_password):
    """使用受限账号，在只读事务中执行查询。"""

    with psycopg.connect(
        host="127.0.0.1",
        port=5433,
        dbname="olist",
        user="olist_reader",
        password=database_password,
        connect_timeout=5,
    ) as connection:

        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '5s'")

            # 最多取 101 行，用于判断结果是否超过展示上限。
            limited_sql = (
                f"SELECT * FROM ({sql_text}) AS query_result LIMIT 101"
            )

            cursor.execute(limited_sql)

            columns = [column.name for column in cursor.description]
            rows = cursor.fetchall()

    return columns, rows


def main():
    guide_path = Path(__file__).with_name("database_guide.txt")
    database_guide = guide_path.read_text(encoding="utf-8-sig")

    api_key = getpass("请输入阿里云百炼 API Key：").strip()
    if not api_key:
        print("API Key 不能为空。")
        return

    question = input("请输入你的数据问题：").strip()
    if not question:
        print("问题不能为空。")
        return

    generated = generate_sql(question, database_guide, api_key).strip()

    print("\n模型生成的内容：")
    print(generated)

    if is_refusal(generated):
        print("当前数据库视图或查询能力不足，未执行查询。")
        return

    try:
        validated_sql = validate_sql(generated)
    except Exception as error:
        print(f"\nSQL 检查未通过：{error}")
        print("本次没有执行数据库查询。")
        return

    print("\n通过检查的 SQL：")
    print(validated_sql)

    confirmation = input("\n是否执行这条查询？输入 y 继续：").strip().lower()
    if confirmation != "y":
        print("已取消查询。")
        return

    database_password = getpass(
        "请输入 olist_reader 的数据库密码："
    )

    try:
        columns, rows = execute_sql(validated_sql, database_password)
    except Exception as error:
        print(f"\n查询失败：{error}")
        return

    print("\n查询结果：")
    print(" | ".join(columns))

    for row in rows[:100]:
        print(" | ".join(str(value) for value in row))

    if not rows:
        print("没有查询结果。")
    elif len(rows) > 100:
        print("结果超过 100 行，仅显示前 100 行。")

    print("\n说明：请结合生成的 SQL 和指标口径核对结果。")


if __name__ == "__main__":
    main()
