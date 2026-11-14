import mlflow


def register(model, name: str, metrics: dict) -> None:
    with mlflow.start_run():
        mlflow.log_metrics(metrics)
        mlflow.sklearn.log_model(model, "model", registered_model_name=name)
