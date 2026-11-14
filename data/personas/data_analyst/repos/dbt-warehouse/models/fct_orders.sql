{{ config(materialized="table") }}

with orders as (
    select * from {{ ref("stg_orders") }}
),
payments as (
    select order_id, sum(amount) as paid from {{ ref("stg_payments") }} group by 1
)
select o.order_id, o.customer_id, o.ordered_at, coalesce(p.paid, 0) as revenue
from orders o
left join payments p using (order_id)
