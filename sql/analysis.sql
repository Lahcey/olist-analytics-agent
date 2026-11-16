-- Run against the existing populated database. These are read-only examples.

-- Monthly product sales and change from the previous available month.
-- LAG skips absent months; use a calendar table for strict calendar-month comparisons.
WITH monthly_sales AS (
    SELECT DATE_TRUNC('month', order_purchase_timestamp)::date AS order_month,
           SUM(product_amount) AS product_sales
    FROM order_analysis
    WHERE order_status = 'delivered'
      AND order_purchase_timestamp >= TIMESTAMP '2017-01-01'
      AND order_purchase_timestamp < TIMESTAMP '2018-09-01'
    GROUP BY 1
)
SELECT order_month, product_sales,
       LAG(product_sales) OVER (ORDER BY order_month) AS previous_sales
FROM monthly_sales ORDER BY order_month;

-- Category sales: use line-item amounts, not the full order payment for each category.
WITH category_sales AS (
    SELECT category_name, SUM(product_amount) AS product_sales
    FROM order_item_category_analysis
    WHERE order_status = 'delivered'
      AND order_purchase_timestamp >= TIMESTAMP '2017-01-01'
      AND order_purchase_timestamp < TIMESTAMP '2018-09-01'
    GROUP BY category_name
)
SELECT category_name, product_sales,
       RANK() OVER (ORDER BY product_sales DESC) AS sales_rank
FROM category_sales ORDER BY sales_rank, category_name;

-- June 2018 within-month repeat customers: at least two delivered orders.
SELECT order_month, monthly_customers, repeat_customers, repeat_customer_pct
FROM monthly_customer_analysis WHERE order_month = DATE '2018-06-01';

-- Delivered orders with both dates: association, not proof of causation.
SELECT delivery_status, COUNT(*) AS orders, COUNT(review_score) AS reviewed_orders,
       ROUND(AVG(review_score), 2) AS avg_score
FROM delivery_review_analysis
WHERE order_purchase_timestamp >= TIMESTAMP '2017-01-01'
  AND order_purchase_timestamp < TIMESTAMP '2018-09-01'
GROUP BY delivery_status ORDER BY delivery_status;
