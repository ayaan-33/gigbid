TENANT_POLICY = """
alter table projects enable row level security;
create policy tenant_isolation on projects
  using (tenant_id = current_setting('app.tenant_id')::uuid);
"""
