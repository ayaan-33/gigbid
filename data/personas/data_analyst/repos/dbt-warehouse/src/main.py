from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

with DAG("daily_kpis", start_date=datetime(2025, 1, 1), schedule="0 6 * * *", catchup=False) as dag:
    extract = PythonOperator(task_id="extract", python_callable=lambda: None, retries=3)
    publish = PythonOperator(task_id="publish", python_callable=lambda: None)
    extract >> publish


def validate(df) -> list[str]:
    problems = []
    if df["id"].duplicated().any():
        problems.append("duplicate ids")
    if df["amount"].lt(0).any():
        problems.append("negative amounts")
    return problems


MONTHLY_REVENUE = """
select date_trunc('month', o.created_at) as month,
       c.region,
       sum(o.amount) as revenue,
       count(distinct o.customer_id) as customers,
       sum(o.amount) / nullif(count(distinct o.customer_id), 0) as arpu
from orders o
join customers c on c.id = o.customer_id
where o.status = 'paid'
group by 1, 2
order by 1, 2
"""


import snowflake.connector


def run(query: str):
    with snowflake.connector.connect(account="xy12345", warehouse="ANALYTICS") as conn:
        return conn.cursor().execute(query).fetchall()


from scipy import stats


def two_proportion_test(conv_a: int, n_a: int, conv_b: int, n_b: int) -> float:
    table = [[conv_a, n_a - conv_a], [conv_b, n_b - conv_b]]
    _, p, _, _ = stats.chi2_contingency(table)
    return p
