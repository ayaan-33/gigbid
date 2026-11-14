import plotly.express as px


def trend_chart(df):
    return px.line(df, x="week", y="value", color="segment", markers=True)


def validate(df) -> list[str]:
    problems = []
    if df["id"].duplicated().any():
        problems.append("duplicate ids")
    if df["amount"].lt(0).any():
        problems.append("negative amounts")
    return problems


from openpyxl import load_workbook


def read_sheet(path: str, sheet: str):
    wb = load_workbook(path, data_only=True)
    return [[c.value for c in row] for row in wb[sheet].iter_rows(min_row=2)]


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
