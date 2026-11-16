from getpass import getpass

import psycopg


password = getpass("请输入 olist_reader 的数据库密码：")

sql = """
SELECT
    COUNT(*) AS order_count,
    SUM(product_amount) AS product_sales
FROM public.order_analysis
WHERE order_status = 'delivered'
  AND order_purchase_timestamp >= %s
  AND order_purchase_timestamp < %s
"""

with psycopg.connect(
    host="127.0.0.1",
    port=5433,
    dbname="olist",
    user="olist_reader",
    password=password,
    connect_timeout=5,
) as connection:
    with connection.cursor() as cursor:
        cursor.execute(sql, ("2017-11-01", "2017-12-01"))
        order_count, product_sales = cursor.fetchone()

print("问题：2017 年 11 月已交付订单的数量和商品销售额是多少？")
print(f"已交付订单数：{order_count}")
print(f"商品销售额：{product_sales}")
print("口径：按下单时间统计，商品销售额不含运费。")