from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

with DAG("daily_kpis", start_date=datetime(2025, 1, 1), schedule="0 6 * * *", catchup=False) as dag:
    extract = PythonOperator(task_id="extract", python_callable=lambda: None, retries=3)
    publish = PythonOperator(task_id="publish", python_callable=lambda: None)
    extract >> publish


from statsmodels.tsa.holtwinters import ExponentialSmoothing


def seasonal_baseline(series, periods: int = 52):
    model = ExponentialSmoothing(series, trend="add", seasonal="add", seasonal_periods=periods)
    return model.fit().forecast(12)


import xgboost as xgb


def train_gbm(X_train, y_train, X_val, y_val):
    model = xgb.XGBClassifier(
        n_estimators=600, max_depth=5, learning_rate=0.05, subsample=0.8,
        scale_pos_weight=(len(y_train) - y_train.sum()) / y_train.sum(), eval_metric="aucpr",
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    return model


import pandas as pd


def build_features(events: pd.DataFrame) -> pd.DataFrame:
    events["month"] = events["ts"].dt.to_period("M")
    agg = events.groupby(["customer_id", "month"]).agg(
        sessions=("session_id", "nunique"), spend=("amount", "sum")
    )
    return agg.groupby(level=0).tail(3).groupby(level=0).mean()
