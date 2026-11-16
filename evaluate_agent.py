"""Small, reproducible evaluation for the Olist question-to-SQL prototype."""

import json
from datetime import datetime
from decimal import Decimal
from getpass import getpass
from pathlib import Path

from ask_database import execute_sql, generate_sql, is_refusal, validate_sql


CASES = [
    {
        "id": "orders_2017_11",
        "question": "2017 年 11 月已交付订单的数量和商品销售额是多少？请按订单数量、商品销售额的顺序返回。",
        "reference": """SELECT COUNT(*), SUM(product_amount) FROM public.order_analysis
            WHERE order_status = 'delivered' AND order_purchase_timestamp >= '2017-11-01'
            AND order_purchase_timestamp < '2017-12-01'""",
    },
    {
        "id": "orders_2018_06",
        "question": "2018 年 6 月已交付订单的数量和商品销售额是多少？请按订单数量、商品销售额的顺序返回。",
        "reference": """SELECT COUNT(*), SUM(product_amount) FROM public.order_analysis
            WHERE order_status = 'delivered' AND order_purchase_timestamp >= '2018-06-01'
            AND order_purchase_timestamp < '2018-07-01'""",
    },
    {
        "id": "category_top3_2017_11",
        "question": "2017 年 11 月已交付订单中，销售额最高的前三个商品品类是什么？请按销售额从高到低排列，每行按品类、商品销售额的顺序返回。",
        "reference": """SELECT category_name, SUM(product_amount) AS sales
            FROM public.order_item_category_analysis WHERE order_status = 'delivered'
            AND order_purchase_timestamp >= '2017-11-01' AND order_purchase_timestamp < '2017-12-01'
            GROUP BY category_name ORDER BY sales DESC, category_name LIMIT 3""",
    },
    {
        "id": "sales_2018_08",
        "question": "2018 年 8 月已交付订单的商品销售额是多少？只返回商品销售额。",
        "reference": """SELECT SUM(product_amount) FROM public.order_analysis
            WHERE order_status = 'delivered' AND order_purchase_timestamp >= '2018-08-01'
            AND order_purchase_timestamp < '2018-09-01'""",
    },
    {
        "id": "unavailable_advertising_cost",
        "question": "2018 年 6 月各广告渠道的广告投放成本是多少？",
        "reference": None,
    },
    {
        "id": "delivery_review_comparison",
        "question": "2017 年 1 月至 2018 年 8 月，按交付状态统计有效评价数和平均评分。请返回交付状态、有效评价数、平均评分，按交付状态升序排列，平均分不要四舍五入。",
        "reference": """SELECT delivery_status, COUNT(review_score), AVG(review_score)
            FROM public.delivery_review_analysis WHERE order_purchase_timestamp >= '2017-01-01'
            AND order_purchase_timestamp < '2018-09-01'
            GROUP BY delivery_status ORDER BY delivery_status ASC""",
    },
    {
        "id": "late_deliveries",
        "question": "2017 年 1 月至 2018 年 8 月下单且已交付的订单中，实际交付日期晚于预计交付日期的订单有多少笔？只返回订单数。",
        "reference": """SELECT COUNT(*) FROM public.delivery_review_analysis
            WHERE order_purchase_timestamp >= '2017-01-01' AND order_purchase_timestamp < '2018-09-01'
            AND delivery_status = 'late'""",
    },
    {
        "id": "unavailable_browse_conversion",
        "question": "2018 年 6 月浏览商品的用户中有多少比例最终购买？",
        "reference": None,
    },
    {
        "id": "monthly_repeat_2018_06",
        "question": "2018 年 6 月有多少不同的真实用户在该月下了两笔或以上已交付订单？只返回月内复购用户数。",
        "reference": """SELECT repeat_customers FROM public.monthly_customer_analysis
            WHERE order_month = DATE '2018-06-01'""",
    },
    {
        "id": "unavailable_cross_month_unique_users",
        "question": "2018 年 5 月和 6 月合计有多少名不同的真实用户下过已交付订单？每名用户只计算一次。",
        "reference": None,
    },
    {
        "id": "unavailable_region_sales",
        "question": "2018 年 6 月巴西各州的商品销售额分别是多少？",
        "reference": None,
    },
]


def normalized_rows(rows):
    """Preserve row/column order, but compare numeric types by value."""
    def normalize(value):
        if value is None:
            return None
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            return Decimal(str(value)).normalize()
        return str(value)
    return [tuple(normalize(value) for value in row) for row in rows]


def main():
    print(f"本测试会最多调用模型 {len(CASES)} 次，并按提示逐条确认查询。")
    print("请先检查免费额度。测试结果只保存在项目文件夹，不保存密钥或数据库密码。")
    if input("输入 y 开始：").strip().lower() != "y":
        return

    api_key = getpass("请输入百炼 API Key：").strip()
    db_password = getpass("请输入 olist_reader 数据库密码：")
    if not api_key or not db_password:
        print("密钥或密码为空，测试已停止。")
        return

    guide = Path(__file__).with_name("database_guide.txt").read_text(encoding="utf-8-sig")
    expected = {}
    try:
        for case in CASES:
            if case["reference"] is not None:
                _, expected[case["id"]] = execute_sql(case["reference"], db_password)
    except Exception as error:
        print(f"参考答案查询失败：{type(error).__name__}。请检查数据库和密码。")
        return

    report = []
    for case in CASES:
        print(f"\n[{case['id']}] {case['question']}")
        record = {"id": case["id"], "question": case["question"]}
        try:
            generated = generate_sql(case["question"], guide, api_key).strip()
            record["generated"] = generated
            print(f"模型输出：\n{generated}")

            if case["reference"] is None:
                record["status"] = "pass" if is_refusal(generated) else "fail_unexpected_answer"
            elif is_refusal(generated):
                record["status"] = "fail_unexpected_refusal"
            else:
                try:
                    checked = validate_sql(generated)
                except Exception as error:
                    record["status"] = "fail_validation"
                    record["error_type"] = type(error).__name__
                    print(f"SQL 检查未通过：{error}")
                else:
                    print(f"检查后的 SQL：\n{checked}")
                    if input("检查 SQL 后，输入 y 执行；其他输入跳过：").strip().lower() != "y":
                        record["status"] = "skipped"
                    else:
                        _, actual = execute_sql(checked, db_password)
                        target = expected[case["id"]]
                        record["actual"] = [[str(v) if v is not None else None for v in row] for row in actual]
                        record["expected"] = [[str(v) if v is not None else None for v in row] for row in target]
                        record["status"] = "pass" if normalized_rows(actual) == normalized_rows(target) else "fail_result"
                        print(f"实际结果：{record['actual']}")
                        print(f"参考结果：{record['expected']}")
        except Exception as error:
            record["status"] = "error"
            record["error_type"] = type(error).__name__
        report.append(record)
        print(f"本题结果：{record['status']}")

    evaluated = [item for item in report if item["status"] != "skipped"]
    passed = sum(item["status"] == "pass" for item in evaluated)
    skipped = len(report) - len(evaluated)
    print(f"\n完成：{passed}/{len(evaluated)} 题通过；跳过 {skipped} 题。")
    by_id = {case["id"]: case for case in CASES}
    for label, is_answerable in (("可回答", True), ("应拒答", False)):
        group = [item for item in report if (by_id[item["id"]]["reference"] is not None) == is_answerable]
        graded = [item for item in group if item["status"] != "skipped"]
        group_passed = sum(item["status"] == "pass" for item in graded)
        print(f"{label}：{group_passed}/{len(graded)} 题通过，跳过 {len(group) - len(graded)} 题。")
    print("测试量较小，结果只适用于这组题目。")
    output = Path(__file__).with_name(f"evaluation_results_{datetime.now():%Y%m%d_%H%M%S}.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"测试记录已保存到：{output.name}")


if __name__ == "__main__":
    main()
