from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


def _sn_field_to_schema(field: Dict[str, object]) -> Dict[str, object]:
    internal_type = str(field.get("internal_type", "string"))
    mapping = {
        "string": {"type": "string"},
        "integer": {"type": "integer"},
        "float": {"type": "number"},
        "decimal": {"type": "number", "format": "double"},
        "boolean": {"type": "boolean"},
        "date": {"type": "string", "format": "date"},
        "datetime": {"type": "string", "format": "date-time"},
        "glide_date_time": {"type": "string", "format": "date-time"},
        "reference": {"type": "string"},
        "journal": {"type": "string"},
        "html": {"type": "string"},
    }
    return mapping.get(internal_type, {"type": "string"})


def synthesize_servicenow_spec(
    *,
    base_url: str,
    dictionaries: Dict[str, List[Dict[str, object]]],
    output_path: str,
    namespace: str | None = None,
    api_name: str | None = None,
    api_version: str | None = None,
) -> str:
    components: Dict[str, object] = {"schemas": {}}
    paths: Dict[str, object] = {}

    for table_name, fields in dictionaries.items():
        schema_props: Dict[str, object] = {}
        required: List[str] = []
        for f in fields:
            element = str(f.get("element"))
            if not element:
                continue
            schema_props[element] = _sn_field_to_schema(f)
            if f.get("mandatory"):
                required.append(element)

        schema_name = f"ServiceNow_{table_name}"
        components["schemas"][schema_name] = {
            "type": "object",
            "properties": schema_props,
            **({"required": required} if required else {}),
        }

        table_base = f"/api/now/table/{table_name}"
        paths[table_base] = {
            "get": {
                "summary": f"List records for {table_name}",
                "parameters": [
                    {"name": "sysparm_limit", "in": "query", "schema": {"type": "integer"}},
                    {"name": "sysparm_query", "in": "query", "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {
                        "description": "OK",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "result": {
                                            "type": "array",
                                            "items": {"$ref": f"#/components/schemas/{schema_name}"},
                                        }
                                    },
                                }
                            }
                        },
                    }
                },
                "security": [{"basic": []}, {"oauth2": []}],
            },
            "post": {
                "summary": f"Create record in {table_name}",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema_name}"}}},
                },
                "responses": {"201": {"description": "Created"}},
                "security": [{"basic": []}, {"oauth2": []}],
            },
        }

        paths[f"{table_base}/{{sys_id}}"] = {
            "get": {
                "summary": f"Get {table_name} by sys_id",
                "parameters": [{"name": "sys_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "OK", "content": {"application/json": {}}}},
                "security": [{"basic": []}, {"oauth2": []}],
            },
            "patch": {
                "summary": f"Update {table_name} by sys_id",
                "parameters": [{"name": "sys_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema_name}"}}},
                },
                "responses": {"200": {"description": "OK"}},
                "security": [{"basic": []}, {"oauth2": []}],
            },
            "delete": {
                "summary": f"Delete {table_name} by sys_id",
                "parameters": [{"name": "sys_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"204": {"description": "No Content"}},
                "security": [{"basic": []}, {"oauth2": []}],
            },
        }

    spec = {
        "openapi": "3.0.3",
        "info": {"title": "ServiceNow Generated API", "version": "0.1.0"},
        "servers": [
            {
                "url": "{server_url}",
                "variables": {"server_url": {"default": base_url}},
            }
        ],
        "security": [{"basic": []}],
        "components": {
            **components,
            "securitySchemes": {
                "basic": {"type": "http", "scheme": "basic"},
                "oauth2": {"type": "oauth2", "flows": {"clientCredentials": {"tokenUrl": "TOKEN_URL", "scopes": {}}}},
            },
        },
        "paths": paths,
        "x-generator": {"name": "api-discovery", "version": "0.1.0"},
    }

    parts = [Path(output_path).parent]
    if namespace:
        parts.append(Path(namespace))
    if api_name:
        parts.append(Path(api_name))
    if api_version:
        parts.append(Path(api_version))
    out_dir = Path(*parts)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / Path(output_path).name
    out = json.dumps(spec, indent=2)
    out_file.write_text(out)
    return str(out_file)

