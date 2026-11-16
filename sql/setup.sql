-- Run only in a NEW, empty PostgreSQL database. /workspace is mounted by Docker.
-- The transaction rolls back if a table creation or CSV import fails.
\set ON_ERROR_STOP on
BEGIN;

CREATE TABLE customers (
    customer_id TEXT, customer_unique_id TEXT, customer_zip_code_prefix TEXT,
    customer_city TEXT, customer_state TEXT
);
CREATE TABLE orders (
    order_id TEXT, customer_id TEXT, order_status TEXT,
    order_purchase_timestamp TIMESTAMP, order_approved_at TIMESTAMP,
    order_delivered_carrier_date TIMESTAMP, order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP
);
CREATE TABLE order_items (
    order_id TEXT, order_item_id INTEGER, product_id TEXT, seller_id TEXT,
    shipping_limit_date TIMESTAMP, price NUMERIC(12,2), freight_value NUMERIC(12,2)
);
CREATE TABLE order_payments (
    order_id TEXT, payment_sequential INTEGER, payment_type TEXT,
    payment_installments INTEGER, payment_value NUMERIC(12,2)
);
CREATE TABLE products (
    product_id TEXT, product_category_name TEXT, product_name_lenght INTEGER,
    product_description_lenght INTEGER, product_photos_qty INTEGER,
    product_weight_g INTEGER, product_length_cm INTEGER, product_height_cm INTEGER,
    product_width_cm INTEGER
);
CREATE TABLE category_translation (
    product_category_name TEXT, product_category_name_english TEXT
);
CREATE TABLE order_reviews (
    review_id TEXT, order_id TEXT, review_score INTEGER, review_comment_title TEXT,
    review_comment_message TEXT, review_creation_date TIMESTAMP, review_answer_timestamp TIMESTAMP
);

\copy customers FROM '/workspace/data/olist_customers_dataset.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy orders FROM '/workspace/data/olist_orders_dataset.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy order_items FROM '/workspace/data/olist_order_items_dataset.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy order_payments FROM '/workspace/data/olist_order_payments_dataset.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy products FROM '/workspace/data/olist_products_dataset.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy category_translation FROM '/workspace/data/product_category_name_translation.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy order_reviews FROM '/workspace/data/olist_order_reviews_dataset.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

CREATE VIEW order_analysis AS
WITH item_totals AS (
    SELECT order_id, COUNT(*) AS item_count, SUM(price) AS product_amount,
           SUM(freight_value) AS freight_amount FROM order_items GROUP BY order_id
), payment_totals AS (
    SELECT order_id, SUM(payment_value) AS payment_amount FROM order_payments GROUP BY order_id
)
SELECT o.order_id, o.customer_id, o.order_status, o.order_purchase_timestamp,
       o.order_delivered_customer_date, o.order_estimated_delivery_date,
       i.item_count, i.product_amount, i.freight_amount, p.payment_amount
FROM orders o LEFT JOIN item_totals i ON o.order_id = i.order_id
LEFT JOIN payment_totals p ON o.order_id = p.order_id;

CREATE VIEW order_item_category_analysis AS
SELECT o.order_id, o.order_status, o.order_purchase_timestamp, i.order_item_id,
       i.product_id, i.price AS product_amount, i.freight_value AS freight_amount,
       p.product_category_name AS category_original,
       COALESCE(t.product_category_name_english, p.product_category_name, '[unknown]') AS category_name
FROM orders o JOIN order_items i ON o.order_id = i.order_id
LEFT JOIN products p ON i.product_id = p.product_id
LEFT JOIN category_translation t ON p.product_category_name = t.product_category_name;

CREATE VIEW delivery_review_analysis AS
WITH ranked_reviews AS (
    SELECT order_id, review_id, review_score, review_answer_timestamp,
           ROW_NUMBER() OVER (PARTITION BY order_id
               ORDER BY review_answer_timestamp DESC, review_id DESC, review_score DESC) AS review_rank
    FROM order_reviews WHERE review_answer_timestamp IS NOT NULL AND review_score BETWEEN 1 AND 5
)
SELECT o.order_id, o.order_purchase_timestamp, o.order_delivered_customer_date,
       o.order_estimated_delivery_date,
       CASE WHEN o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date
            THEN 'late' ELSE 'on_time' END AS delivery_status,
       r.review_score
FROM orders o LEFT JOIN ranked_reviews r ON o.order_id = r.order_id AND r.review_rank = 1
WHERE o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
  AND o.order_estimated_delivery_date IS NOT NULL;

CREATE VIEW monthly_customer_analysis AS
WITH monthly_user_orders AS (
    SELECT DATE_TRUNC('month', o.order_purchase_timestamp)::date AS order_month,
           c.customer_unique_id, COUNT(*) AS order_count
    FROM orders o JOIN customers c ON o.customer_id = c.customer_id
    WHERE o.order_status = 'delivered' AND o.order_purchase_timestamp IS NOT NULL
      AND c.customer_unique_id IS NOT NULL
    GROUP BY DATE_TRUNC('month', o.order_purchase_timestamp)::date, c.customer_unique_id
)
SELECT order_month, COUNT(*) AS monthly_customers,
       COUNT(*) FILTER (WHERE order_count >= 2) AS repeat_customers,
       ROUND(COUNT(*) FILTER (WHERE order_count >= 2)::numeric / NULLIF(COUNT(*), 0) * 100, 2)
           AS repeat_customer_pct
FROM monthly_user_orders GROUP BY order_month;

CREATE VIEW customer_purchase_sequence_2017_2018 AS
SELECT c.customer_unique_id, o.order_id, o.order_purchase_timestamp,
       ROW_NUMBER() OVER (PARTITION BY c.customer_unique_id
           ORDER BY o.order_purchase_timestamp, o.order_id) AS purchase_number,
       LEAD(o.order_purchase_timestamp) OVER (PARTITION BY c.customer_unique_id
           ORDER BY o.order_purchase_timestamp, o.order_id) AS next_order_time
FROM orders o JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered' AND o.order_purchase_timestamp >= TIMESTAMP '2017-01-01'
  AND o.order_purchase_timestamp < TIMESTAMP '2018-09-01' AND c.customer_unique_id IS NOT NULL;

COMMIT;
