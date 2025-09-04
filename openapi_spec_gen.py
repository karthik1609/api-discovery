import os, json, sys, textwrap, re
from typing import Any, Dict
from jsonschema import validate as jsonschema_validate, ValidationError
from openai import AzureOpenAI

from dotenv import load_dotenv
load_dotenv()

# ---- Azure OpenAI config ----
# Required env vars:
# AZURE_OPENAI_ENDPOINT="https://<your-resource-name>.openai.azure.com"
# AZURE_OPENAI_API_KEY="<key>"
# AZURE_OPENAI_API_VERSION="2024-10-21"   # or the current v1 version available to you
# AZURE_OPENAI_DEPLOYMENT="<your-deployment-name>"  # e.g., gpt-4o-mini, gpt-4.1-mini, etc.



# ---- Inputs / outputs ----
MARKDOWN_PATH = sys.argv[1] if len(sys.argv) > 1 else "table_api.md"
OUT_JSON = sys.argv[2] if len(sys.argv) > 2 else "openapi.json"
OUT_YAML = sys.argv[3] if len(sys.argv) > 3 else "openapi.yaml"

# ---- Minimal but strict JSON Schema for OpenAPI 3.1 scaffolding ----
# We keep it opinionated on the top-level keys and permissive underneath so that the
# model can freely populate methods/parameters/examples, while we still guarantee a
# proper OpenAPI shape and valid JSON output.
OPENAPI_JSON_SCHEMA: Dict[str, Any] = {
    "name": "OpenAPISpec",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["openapi", "info", "paths"],
        "properties": {
            "openapi": {"type": "string", "const": "3.1.0"},
            "info": {
                "type": "object",
                "required": ["title", "version"],
                "additionalProperties": True,
                "properties": {
                    "title": {"type": "string"},
                    "version": {"type": "string"},
                    "summary": {"type": "string"},
                    "description": {"type": "string"}
                }
            },
            "servers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["url"],
                    "additionalProperties": True,
                    "properties": {
                        "url": {"type": "string"},
                        "description": {"type": "string"}
                    }
                }
            },
            "paths": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "description": "A Path Item Object with HTTP methods.",
                    "additionalProperties": {
                        "type": "object",
                        "description": "Operation Object",
                        "additionalProperties": True
                    }
                }
            },
            "components": {
                "type": "object",
                "additionalProperties": True
            },
            "tags": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True}
            },
            "x_source_notes": {
                "type": "object",
                "additionalProperties": True,
                "description": "Provenance/notes the model includes; safe to remove later."
            }
        }
    },
    # Optional: ask the model to be as strict as possible
    "strict": True,
}

SYSTEM_INSTRUCTIONS = """\
You convert vendor REST documentation into a clean OpenAPI 3.1 spec.
Rules:
- Output ONLY JSON that conforms to the provided json_schema.
- Prefer concise summaries; do not copy legalese or UI fluff.
- Include realistic server URLs as placeholders if needed, e.g. "https://{instance}.servicenow.com".
- Use tags sensibly (e.g., Table).
- Capture request/response bodies, parameters (query, path), headers, status codes.
- Prefer canonical parameter names (sysparm_* etc.) and note enums/defaults when present.
- Add minimal components/schemas where repeated shapes are implied (e.g., generic result envelope).
- Do NOT invent endpoints not implied by the source text.
"""

USER_TEMPLATE = """\
Source: ServiceNow Table API (Washington DC docs, scraped)
Goal: produce an OpenAPI 3.1 JSON spec for the documented endpoints.

Scope guidance:
- Include: DELETE /now/table/{{tableName}}/{{sys_id}}; GET /now/table/{{tableName}}; 
  GET /now/table/{{tableName}}/{{sys_id}}; PATCH /now/table/{{tableName}}/{{sys_id}};
  POST /now/table/{{tableName}}; PUT /now/table/{{tableName}}/{{sys_id}}
- Use base server url: https://{{instance}}.servicenow.com/api   (document as a variable)
- Group operations under the tag "Table".
- Represent shared query params (e.g., sysparm_* family) via components/parameters if helpful.
- Where examples are shown in the doc, include a short example request/response.

Now the raw markdown (truncate UI noise, keep technical details):

----------------(BEGIN MARKDOWN)----------------
{md}
-----------------(END MARKDOWN)-----------------
"""

def main():
    with open(MARKDOWN_PATH, "r", encoding="utf-8") as f:
        md = f.read()

    # (Optional) a little trimming to avoid sending noise
    md_clean = md.replace("\u00a0", " ").strip()

    try:
        client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        )
        model = os.environ["AZURE_OPENAI_DEPLOYMENT"]
    except KeyError as e:
        missing = str(e).strip("'")
        print(f"ERROR: Missing Azure OpenAI env var: {missing}", file=sys.stderr)
        sys.exit(1)

    messages = [
        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
        {"role": "user", "content": USER_TEMPLATE.format(md=md_clean[:120000])}  # safety cap
    ]

    def _try_parse_json(s: str) -> Dict[str, Any]:
        # direct parse
        try:
            return json.loads(s)
        except Exception:
            pass
        # extract largest JSON object
        m = re.search(r"\{[\s\S]*\}$", s.strip())
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        raise ValueError("Model response was not valid JSON")

    def call_with_fallbacks() -> Dict[str, Any]:
        # 1) Try structured outputs json_schema
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                response_format={
                    "type": "json_schema",
                    "json_schema": OPENAPI_JSON_SCHEMA,
                },
            )
            return _try_parse_json(resp.choices[0].message.content)
        except Exception as e:
            err = str(e)
            # 2) Fallback to json_object (if supported)
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_object"},
                )
                return _try_parse_json(resp.choices[0].message.content)
            except Exception:
                pass
            # 3) Final fallback: no special response_format, strong instruction
            messages_fallback = [
                messages[0],  # system
                {"role": "user", "content": messages[1]["content"] + "\n\nReturn ONLY valid JSON, no prose."},
            ]
            resp = client.chat.completions.create(
                model=model,
                messages=messages_fallback,
                temperature=0,
            )
            return _try_parse_json(resp.choices[0].message.content)

    spec = call_with_fallbacks()

    # Validate against our JSON schema (best-effort)
    try:
        jsonschema_validate(instance=spec, schema=OPENAPI_JSON_SCHEMA["schema"])
    except ValidationError as ve:
        print(f"WARN: Model output did not fully validate against schema: {ve.message}", file=sys.stderr)

    # Write JSON
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)

    # Also write YAML (no external deps; a tiny encoder)
    def to_yaml(obj, indent=0):
        sp = "  " * indent
        if isinstance(obj, dict):
            lines = []
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    lines.append(f"{sp}{k}:")
                    lines.append(to_yaml(v, indent + 1))
                else:
                    # JSON-like scalars
                    if isinstance(v, str):
                        # quote only if needed
                        if any(ch in v for ch in [":", "{", "}", "[", "]", "#", ",", "\n", "\""]):
                            vq = json.dumps(v, ensure_ascii=False)
                        else:
                            vq = v
                        lines.append(f"{sp}{k}: {vq}")
                    else:
                        lines.append(f"{sp}{k}: {json.dumps(v, ensure_ascii=False)}")
            return "\n".join(lines)
        elif isinstance(obj, list):
            lines = []
            for item in obj:
                if isinstance(item, (dict, list)):
                    lines.append(f"{sp}-")
                    lines.append(to_yaml(item, indent + 1))
                else:
                    if isinstance(item, str):
                        if any(ch in item for ch in [":", "{", "}", "[", "]", "#", ",", "\n", "\""]):
                            vq = json.dumps(item, ensure_ascii=False)
                        else:
                            vq = item
                        lines.append(f"{sp}- {vq}")
                    else:
                        lines.append(f"{sp}- {json.dumps(item, ensure_ascii=False)}")
            return "\n".join(lines)
        else:
            return f"{sp}{json.dumps(obj, ensure_ascii=False)}"

    with open(OUT_YAML, "w", encoding="utf-8") as f:
        f.write(to_yaml(spec))

    print(f"Wrote {OUT_JSON} and {OUT_YAML}")

if __name__ == "__main__":
    main()
