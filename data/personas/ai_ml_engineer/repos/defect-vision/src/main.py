import cv2
import timm

model = timm.create_model("efficientnet_b0", pretrained=True, num_classes=2)


def preprocess(path: str):
    img = cv2.imread(path)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return cv2.resize(img, (224, 224))


import mlflow


def register(model, name: str, metrics: dict) -> None:
    with mlflow.start_run():
        mlflow.log_metrics(metrics)
        mlflow.sklearn.log_model(model, "model", registered_model_name=name)


import torch
from torch import nn


class Head(nn.Module):
    def __init__(self, dim: int, n_classes: int):
        super().__init__()
        self.net = nn.Sequential(nn.Dropout(0.2), nn.Linear(dim, n_classes))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)
