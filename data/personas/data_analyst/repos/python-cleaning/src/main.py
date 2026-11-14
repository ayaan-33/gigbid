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


import pytest


@pytest.mark.parametrize("value,expected", [(0, 0), (10, 10)])
def test_identity(value, expected):
    assert value == expected


import pandas as pd


def build_features(events: pd.DataFrame) -> pd.DataFrame:
    events["month"] = events["ts"].dt.to_period("M")
    agg = events.groupby(["customer_id", "month"]).agg(
        sessions=("session_id", "nunique"), spend=("amount", "sum")
    )
    return agg.groupby(level=0).tail(3).groupby(level=0).mean()
