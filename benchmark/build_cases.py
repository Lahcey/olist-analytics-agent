"""Build aggregate-only benchmark references from the source tables (no model calls)."""
from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from getpass import getpass
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent
START, END = '2017-01-01', '2018-09-01'

BASE_SQL = """
WITH items AS (SELECT order_id, SUM(price) product, SUM(freight_value) freight FROM order_items GROUP BY order_id),
payments AS (SELECT order_id, SUM(payment_value) payment FROM order_payments GROUP BY order_id)
SELECT date_trunc('month', o.order_purchase_timestamp)::date AS order_month, count(*) n,
       sum(i.product) product, sum(i.freight) freight, sum(p.payment) payment, avg(i.product) avg_product
FROM orders o LEFT JOIN items i ON o.order_id=i.order_id LEFT JOIN payments p ON o.order_id=p.order_id
WHERE o.order_status='delivered' AND o.order_purchase_timestamp >= %s AND o.order_purchase_timestamp < %s
GROUP BY 1 ORDER BY 1
"""
CATEGORY_SQL = """
SELECT date_trunc('month', o.order_purchase_timestamp)::date AS order_month,
       coalesce(t.product_category_name_english,p.product_category_name,'[unknown]') category,
       sum(i.price) sales
FROM orders o JOIN order_items i ON o.order_id=i.order_id
LEFT JOIN products p ON p.product_id=i.product_id
LEFT JOIN category_translation t ON t.product_category_name=p.product_category_name
WHERE o.order_status='delivered' AND o.order_purchase_timestamp >= %s AND o.order_purchase_timestamp < %s
GROUP BY 1,2 ORDER BY 1,3 DESC,2
"""
DELIVERY_SQL = """
WITH reviews AS (
 SELECT order_id, review_score,
 row_number() OVER (PARTITION BY order_id ORDER BY review_answer_timestamp DESC, review_id DESC, review_score DESC) rn
 FROM order_reviews WHERE review_answer_timestamp IS NOT NULL AND review_score BETWEEN 1 AND 5
)
SELECT date_trunc('month',o.order_purchase_timestamp)::date AS order_month,
 CASE WHEN o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date THEN 'late' ELSE 'on_time' END status,
 count(*) n, count(r.review_score) reviewed, avg(r.review_score) avg_score
FROM orders o LEFT JOIN reviews r ON o.order_id=r.order_id AND r.rn=1
WHERE o.order_status='delivered' AND o.order_delivered_customer_date IS NOT NULL
 AND o.order_estimated_delivery_date IS NOT NULL AND o.order_purchase_timestamp >= %s AND o.order_purchase_timestamp < %s
GROUP BY 1,2 ORDER BY 1,2
"""
CUSTOMER_SQL = """
WITH per_user AS (
 SELECT date_trunc('month',o.order_purchase_timestamp)::date AS order_month,c.customer_unique_id,count(*) n
 FROM orders o JOIN customers c ON o.customer_id=c.customer_id
 WHERE o.order_status='delivered' AND c.customer_unique_id IS NOT NULL
 AND o.order_purchase_timestamp >= %s AND o.order_purchase_timestamp < %s
 GROUP BY 1,2
)
SELECT order_month,count(*) customers,count(*) FILTER (WHERE n>=2) repeats,
 round(count(*) FILTER (WHERE n>=2)::numeric / nullif(count(*),0)*100,2) pct
FROM per_user GROUP BY order_month ORDER BY order_month
"""


def make_cases(conn):
    with conn.cursor() as cur:
        def fetch(q):
            cur.execute(q, (START, END))
            return cur.fetchall()
        base = {r[0]: r for r in fetch(BASE_SQL)}
        cats = {}
        for month, category, sales in fetch(CATEGORY_SQL):
            cats.setdefault(month, []).append((category, sales))
        delivery = {}
        for month, status, n, reviewed, score in fetch(DELIVERY_SQL):
            delivery.setdefault(month, {})[status] = (n, reviewed, score)
        customers = {r[0]: r for r in fetch(CUSTOMER_SQL)}

    def enc(rows):
        return [[str(v) if isinstance(v, (Decimal, date)) else v for v in row] for row in rows]

    cases = []
    for year in (2017, 2018):
        for month in range(1, 13 if year == 2017 else 9):
            d = date(year, month, 1)
            nxt = date(year + (month == 12), month % 12 + 1, 1)
            start, end = d.isoformat(), nxt.isoformat()
            b, c = base[d], customers[d]
            ds = delivery[d]
            hc = next((value for category, value in cats[d] if category == 'health_beauty'), None)
            assert hc is not None and 'late' in ds and 'on_time' in ds
            when = f"{year}年{month}月"
            entries = [
                ('order_count', f'{when}已交付订单有多少笔？只返回订单数。', [(b[1],)]),
                ('product_sales', f'{when}已交付订单的商品销售额是多少？不含运费，只返回商品销售额。', [(b[2],)]),
                ('freight', f'{when}已交付订单的运费总金额是多少？只返回运费总额。', [(b[3],)]),
                ('payment', f'{when}已交付订单的支付总金额是多少？只返回支付总额。', [(b[4],)]),
                ('average_product', f'{when}已交付订单的平均订单商品金额是多少？不含运费，不要四舍五入，只返回平均值。', [(b[5],)]),
                ('category_top3', f'{when}已交付订单的商品销售额最高的前三个品类是什么？按销售额降序、品类名升序排列，依次返回品类和销售额。', cats[d][:3]),
                ('category_health', f'{when}已交付订单中 health_beauty 品类的商品销售额是多少？只返回金额。', [(hc,)]),
                ('late_orders', f'{when}下单且已交付的订单中，实际交付日期晚于预计交付日期的有多少笔？只返回订单数。', [(ds['late'][0],)]),
                ('delivery_reviews', f'{when}下单的已交付订单，分别统计按时和延迟交付的有效评价数与平均评分。依次返回交付状态、评价数和平均评分，按交付状态升序排列，不要四舍五入。', [(s, ds[s][1], ds[s][2]) for s in sorted(ds)]),
                ('monthly_users', f'{when}至少下过一笔已交付订单的不同用户有多少人？只返回用户数。', [(c[1],)]),
                ('monthly_repeat', f'{when}同一个月内下了两笔或以上已交付订单的不同用户有多少？只返回月内复购人数。', [(c[2],)]),
                ('monthly_repeat_pct', f'{when}已交付订单用户中，同月下了两笔或以上已交付订单的用户占比百分数是多少？只返回百分比数值。', [(c[3],)]),
            ]
            for family, question, rows in entries:
                cases.append({'id': f'{family}_{year}{month:02}', 'family': family,
                              'period': start, 'kind': 'answerable', 'question': question,
                              'expected_rows': enc(rows)})

    # All refusal cases require information not accessible in the four authorized views.
    refusals = {
      'ads': lambda m: f'2018年{m}月各广告渠道的投放成本是多少？',
      'views': lambda m: f'2018年{m}月商品浏览用户中有多少比例完成购买？',
      'cross_month_users': lambda m: f'2018年{m}月与{m+1}月合计有多少不同用户下了已交付订单，每人只计一次？',
      'region': lambda m: f'2018年{m}月巴西各州的商品销售额分别是多少？',
      'profit': lambda m: f'2018年{m}月的商品采购成本和销售利润分别是多少？',
      'user_age': lambda m: f'2018年{m}月已交付订单用户的平均年龄是多少？',
      '24h_repeat': lambda m: f'2018年{m}月有多少用户在首笔订单至少24小时后再次下已交付订单？',
      'traffic_source': lambda m: f'2018年{m}月通过搜索引擎进入网站的已交付订单数量是多少？',
    }
    for family, make_question in refusals.items():
        for month in range(1, 6):
            cases.append({'id': f'refuse_{family}_2018{month:02}', 'family': 'refuse_' + family,
                          'period': f'2018-{month:02}-01', 'kind': 'unanswerable',
                          'question': make_question(month), 'expected_rows': None})
    assert len(cases) == 280 and len({c['id'] for c in cases}) == 280
    return cases


def main():
    password = getpass('请输入本地 olist_admin 数据库密码：')
    with psycopg.connect(host='127.0.0.1', port=5433, dbname='olist', user='olist_admin',
                         password=password, options='-c default_transaction_read_only=on', connect_timeout=5) as conn:
        cases = make_cases(conn)
    ROOT.mkdir(exist_ok=True)
    (ROOT / 'cases.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False)+'\n' for c in cases), encoding='utf-8')
    with (ROOT / 'cases.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id','family','period','kind','question','expected_rows'])
        writer.writeheader()
        for c in cases:
            writer.writerow({**c, 'expected_rows': json.dumps(c['expected_rows'], ensure_ascii=False)})
    print(f'已生成 {len(cases)} 道测试题，未调用模型。')


if __name__ == '__main__':
    main()
