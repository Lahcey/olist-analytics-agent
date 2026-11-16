from getpass import getpass

import psycopg


password = getpass("请输入 olist_reader 的数据库密码：")

with psycopg.connect(
    host="127.0.0.1",
    port=5433,
    dbname="olist",
    user="olist_reader",
    password=password,
    connect_timeout=5,
) as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                current_user,
                current_setting('transaction_read_only')
            """
        )
        username, read_only = cursor.fetchone()

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM public.order_analysis
            """
        )
        order_count = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT
                has_table_privilege(
                    current_user,
                    'public.orders',
                    'SELECT'
                )
            """
        )
        can_read_raw_orders = cursor.fetchone()[0]

print(f"连接成功，当前账号：{username}")
print(f"当前事务是否只读：{read_only}")
print(f"订单分析视图行数：{order_count}")
print(f"是否能直接读取原始 orders 表：{can_read_raw_orders}")