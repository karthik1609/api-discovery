Automated OpenAPI spec generation for ServiceNow, Salesforce, and Pega.

Quickstart

1) Install

```
uv sync --all-extras --dev
```

2) Discover and synthesize ServiceNow (P0)

```
uv run api-discovery discover-and-synthesize servicenow \
  --base-url https://YOUR_INSTANCE.service-now.com \
  --username $SERVICENOW_USERNAME \
  --password $SERVICENOW_PASSWORD \
  --out openapi_specs/servicenow_generated.json
```

3) Validate spec

```
uv run api-discovery validate-spec --path openapi_specs/servicenow_generated.json
```

Status tracker

The state file at `.state/servicenow/state.json` tracks known/unknown resources, verification status, and evidence.

