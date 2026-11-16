"""Cross-check frozen answers against the four read-only views, without model calls."""
import json
import sys
from getpass import getpass
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from benchmark.run_benchmark import compare_rows


def main():
    password = getpass('请输入 olist_reader 数据库密码：')
    cases = [json.loads(line) for line in (ROOT/'benchmark'/'cases.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    with psycopg.connect(host='127.0.0.1', port=5433, dbname='olist', user='olist_reader', password=password,
                         connect_timeout=5, options='-c default_transaction_read_only=on') as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT date_trunc('month',order_purchase_timestamp)::date, count(*),
                sum(product_amount),sum(freight_amount),sum(payment_amount),avg(product_amount)
                FROM public.order_analysis WHERE order_status='delivered'
                AND order_purchase_timestamp >= '2017-01-01' AND order_purchase_timestamp < '2018-09-01'
                GROUP BY 1 ORDER BY 1""")
            base = {r[0].isoformat():r for r in cur.fetchall()}
            cur.execute("""SELECT date_trunc('month',order_purchase_timestamp)::date, category_name, sum(product_amount)
                FROM public.order_item_category_analysis WHERE order_status='delivered'
                AND order_purchase_timestamp >= '2017-01-01' AND order_purchase_timestamp < '2018-09-01'
                GROUP BY 1,2 ORDER BY 1,3 DESC,2""")
            categories = {}
            for month, category, sales in cur.fetchall():
                categories.setdefault(month.isoformat(), []).append((category, sales))
            cur.execute("""SELECT date_trunc('month',order_purchase_timestamp)::date, delivery_status,
                count(*),count(review_score),avg(review_score) FROM public.delivery_review_analysis
                WHERE order_purchase_timestamp >= '2017-01-01' AND order_purchase_timestamp < '2018-09-01'
                GROUP BY 1,2 ORDER BY 1,2""")
            deliveries = {}
            for month, status, n, reviewed, score in cur.fetchall():
                deliveries.setdefault(month.isoformat(), {})[status] = (n, reviewed, score)
            cur.execute("""SELECT order_month,monthly_customers,repeat_customers,repeat_customer_pct
                FROM public.monthly_customer_analysis WHERE order_month >= '2017-01-01'
                AND order_month < '2018-09-01' ORDER BY order_month""")
            customers = {r[0].isoformat():r for r in cur.fetchall()}
    errors = []
    answerable = [c for c in cases if c['kind'] == 'answerable']
    for case in answerable:
        month, family = case['period'], case['family']
        b, c, ds = base[month], customers[month], deliveries[month]
        view_rows = {
            'order_count': [(b[1],)], 'product_sales': [(b[2],)], 'freight': [(b[3],)],
            'payment': [(b[4],)], 'average_product': [(b[5],)], 'category_top3': categories[month][:3],
            'category_health': [(next((sales for name,sales in categories[month] if name=='health_beauty'), None),)],
            'late_orders': [(ds['late'][0],)],
            'delivery_reviews': [(status, ds[status][1], ds[status][2]) for status in sorted(ds)],
            'monthly_users': [(c[1],)], 'monthly_repeat': [(c[2],)], 'monthly_repeat_pct': [(c[3],)],
        }[family]
        if not compare_rows(view_rows, case['expected_rows']):
            errors.append(case['id'])
    print(f'可回答题答案对账：{len(answerable)-len(errors)}/{len(answerable)} 一致。')
    if errors:
        print('不一致题目：', ', '.join(errors))
        raise SystemExit(1)
    print('该检查对照原始表聚合与分析视图，不评估模型或应拒答题。')


if __name__ == '__main__':
    main()
