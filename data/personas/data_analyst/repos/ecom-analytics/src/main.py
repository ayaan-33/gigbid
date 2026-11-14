from openpyxl import load_workbook


def read_sheet(path: str, sheet: str):
    wb = load_workbook(path, data_only=True)
    return [[c.value for c in row] for row in wb[sheet].iter_rows(min_row=2)]


from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest


def sessions_by_channel(property_id: str):
    client = BetaAnalyticsDataClient()
    req = RunReportRequest(property=f"properties/{property_id}",
                           dimensions=[Dimension(name="sessionDefaultChannelGroup")],
                           metrics=[Metric(name="sessions"), Metric(name="conversions")],
                           date_ranges=[DateRange(start_date="28daysAgo", end_date="today")])
    return client.run_report(req)


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
