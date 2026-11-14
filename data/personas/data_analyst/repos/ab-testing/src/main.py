import plotly.express as px


def trend_chart(df):
    return px.line(df, x="week", y="value", color="segment", markers=True)


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


from scipy import stats


def two_proportion_test(conv_a: int, n_a: int, conv_b: int, n_b: int) -> float:
    table = [[conv_a, n_a - conv_a], [conv_b, n_b - conv_b]]
    _, p, _, _ = stats.chi2_contingency(table)
    return p


import pandas as pd


def build_features(events: pd.DataFrame) -> pd.DataFrame:
    events["month"] = events["ts"].dt.to_period("M")
    agg = events.groupby(["customer_id", "month"]).agg(
        sessions=("session_id", "nunique"), spend=("amount", "sum")
    )
    return agg.groupby(level=0).tail(3).groupby(level=0).mean()
