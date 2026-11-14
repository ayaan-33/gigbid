"""Print FastAPI's OpenAPI schema (used by `make client` to regenerate the TS client)."""

import json

from apps.api.main import app

print(json.dumps(app.openapi(), indent=1))
