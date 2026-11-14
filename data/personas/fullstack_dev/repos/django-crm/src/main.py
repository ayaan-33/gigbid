from celery import Celery

app = Celery("tasks", broker="redis://localhost:6379/0")


@app.task(bind=True, max_retries=3, acks_late=True)
def process(self, item_id: str) -> str:
    return item_id


from django.db import models


class Deal(models.Model):
    account = models.ForeignKey("Account", on_delete=models.CASCADE)
    stage = models.CharField(max_length=32, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)


TENANT_POLICY = """
alter table projects enable row level security;
create policy tenant_isolation on projects
  using (tenant_id = current_setting('app.tenant_id')::uuid);
"""
