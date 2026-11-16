-- Run as olist_admin after creating the olist_reader login role.
-- The role should NOT be a superuser or inherit elevated privileges.
GRANT CONNECT ON DATABASE olist TO olist_reader;
GRANT USAGE ON SCHEMA public TO olist_reader;
GRANT SELECT ON public.order_analysis TO olist_reader;
GRANT SELECT ON public.order_item_category_analysis TO olist_reader;
GRANT SELECT ON public.delivery_review_analysis TO olist_reader;
GRANT SELECT ON public.monthly_customer_analysis TO olist_reader;
ALTER ROLE olist_reader SET default_transaction_read_only = on;
