import mlflow


def register(model, name: str, metrics: dict) -> None:
    with mlflow.start_run():
        mlflow.log_metrics(metrics)
        mlflow.sklearn.log_model(model, "model", registered_model_name=name)


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


import xgboost as xgb


def train_gbm(X_train, y_train, X_val, y_val):
    model = xgb.XGBClassifier(
        n_estimators=600, max_depth=5, learning_rate=0.05, subsample=0.8,
        scale_pos_weight=(len(y_train) - y_train.sum()) / y_train.sum(), eval_metric="aucpr",
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    return model
