CREATE ROLE metric_reader LOGIN PASSWORD 'demo_read';
ALTER ROLE metric_reader SET default_transaction_read_only = on;
CREATE ROLE app_user LOGIN PASSWORD 'demo_app';
