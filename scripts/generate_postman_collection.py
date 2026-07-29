#!/usr/bin/env python3
"""Genera colección Postman v2.1 desde el OpenAPI de FastAPI.

Uso:
  python scripts/generate_postman_collection.py
  python scripts/generate_postman_collection.py --url https://epoint-crm-backend-7d70ac333373.herokuapp.com/openapi.json
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT.parent / "docs" / "postman"

DEFAULT_PROD = "https://epoint-crm-backend-7d70ac333373.herokuapp.com"
DEFAULT_STAGING = "https://dev-epoint-crm-backend-3807e7e86dca.herokuapp.com"

# Ejemplos útiles para requests frecuentes
EXAMPLE_BODIES: dict[str, dict] = {
    "post /api/v1/auth/login": {
        "email": "admin@epoint.com",
        "password": "Admin123!",
    },
    "post /api/v1/auth/bootstrap-admin": {
        "email": "tu-admin@epointcorporation.com",
        "password": "CambiaEsto123!",
        "first_name": "Admin",
        "last_name": "Producción",
        "phone": None,
    },
    "post /api/v1/auth/refresh": {
        "refresh_token": "{{refresh_token}}",
    },
    "post /api/v1/auth/forgot-password": {
        "email": "admin@epoint.com",
    },
}


def load_openapi(url: str | None, path: Path | None) -> dict:
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if not url:
        raise SystemExit("Necesitás --url o un openapi.json local")
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def schema_example(schema: dict, components: dict) -> object:
    if not schema:
        return {}
    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        return schema_example(components.get("schemas", {}).get(ref, {}), components)
    if "example" in schema:
        return schema["example"]
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        out = {}
        for key, prop in props.items():
            if key in required or len(out) < 8:
                out[key] = schema_example(prop, components)
        return out
    if t == "array":
        return [schema_example(schema.get("items") or {}, components)]
    if t == "integer":
        return 1
    if t == "number":
        return 1.0
    if t == "boolean":
        return True
    if schema.get("format") == "email":
        return "user@example.com"
    if t == "string":
        return schema.get("default") or "string"
    return None


def path_to_segments(path: str) -> list[dict]:
    parts = [p for p in path.strip("/").split("/") if p]
    segs = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            segs.append({"type": "string", "value": f"{{{{{name}}}}}"})
        else:
            segs.append({"type": "string", "value": part})
    return segs


def build_url(path: str, query_params: list[dict]) -> dict:
    raw = "{{baseUrl}}" + path
    # path params → {{id}} style already in path_to_segments
    path_for_raw = re.sub(r"\{([^}]+)\}", r"{{\1}}", path)
    raw = "{{baseUrl}}" + path_for_raw
    return {
        "raw": raw + (("?" + "&".join(f"{q['key']}={q['value']}" for q in query_params)) if query_params else ""),
        "host": ["{{baseUrl}}"],
        "path": [re.sub(r"\{([^}]+)\}", r"{{\1}}", p) for p in path.strip("/").split("/") if p],
        "query": query_params,
    }


def op_to_item(path: str, method: str, op: dict, components: dict) -> dict:
    name = op.get("summary") or f"{method.upper()} {path}"
    key = f"{method.lower()} {path}"
    headers = [{"key": "Content-Type", "value": "application/json", "type": "text"}]
    if path.endswith("/bootstrap-admin"):
        headers.append(
            {
                "key": "X-Bootstrap-Token",
                "value": "{{bootstrap_admin_token}}",
                "type": "text",
            }
        )

    query_params: list[dict] = []
    for param in op.get("parameters") or []:
        if "$ref" in param:
            ref = param["$ref"].split("/")[-1]
            param = (components.get("parameters") or {}).get(ref, {})
        loc = param.get("in")
        pname = param.get("name", "param")
        if loc == "query":
            query_params.append(
                {
                    "key": pname,
                    "value": "",
                    "description": param.get("description") or "",
                    "disabled": not param.get("required", False),
                }
            )
        elif loc == "header" and pname.lower() not in ("authorization", "content-type"):
            headers.append(
                {
                    "key": pname,
                    "value": f"{{{{{pname}}}}}",
                    "description": param.get("description") or "",
                    "disabled": not param.get("required", False),
                }
            )

    body = None
    rb = op.get("requestBody") or {}
    content = rb.get("content") or {}
    json_media = content.get("application/json") or next(iter(content.values()), None)
    if json_media is not None:
        example = EXAMPLE_BODIES.get(key)
        if example is None:
            example = schema_example(json_media.get("schema") or {}, components)
        body = {
            "mode": "raw",
            "raw": json.dumps(example, ensure_ascii=False, indent=2),
            "options": {"raw": {"language": "json"}},
        }

    request: dict = {
        "method": method.upper(),
        "header": headers,
        "url": build_url(path, query_params),
        "description": op.get("description") or "",
    }
    if body is not None:
        request["body"] = body

    # Auth: public endpoints without bearer
    public = {
        "post /api/v1/auth/login",
        "post /api/v1/auth/bootstrap-admin",
        "post /api/v1/auth/2fa/verify",
        "post /api/v1/auth/forgot-password",
        "post /api/v1/auth/reset-password",
        "post /api/v1/auth/refresh",
        "get /api/v1/health",
    }
    if key.startswith("get /api/v1/branding/") or key in public or "/webhooks/" in path or "/pagar" in path:
        request["auth"] = {"type": "noauth"}

    return {"name": name, "request": request, "response": []}


def build_collection(openapi: dict, base_url: str) -> dict:
    components = openapi.get("components") or {}
    folders: dict[str, list] = {}
    for path, methods in sorted((openapi.get("paths") or {}).items()):
        for method, op in methods.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            tags = op.get("tags") or ["Otros"]
            tag = tags[0]
            folders.setdefault(tag, []).append(op_to_item(path, method, op, components))

    items = [{"name": tag, "item": reqs} for tag, reqs in sorted(folders.items())]

    return {
        "info": {
            "name": "ePoint CRM API",
            "description": (
                "Colección generada desde OpenAPI.\n\n"
                "1. Elegí el environment (Production / Staging).\n"
                "2. Corré **Autenticación → Login**.\n"
                "3. Copiá `access_token` a la variable `access_token` del environment "
                "(o usá un test script).\n"
                "4. Para crear ADMIN: **Autenticación → Crear usuario ADMIN (token de bootstrap)** "
                "con header `X-Bootstrap-Token` = `bootstrap_admin_token`.\n"
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}],
        },
        "variable": [
            {"key": "baseUrl", "value": base_url},
            {"key": "access_token", "value": ""},
            {"key": "refresh_token", "value": ""},
            {"key": "bootstrap_admin_token", "value": ""},
        ],
        "item": items,
        "event": [
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "try {",
                        "  const j = pm.response.json();",
                        "  if (j.access_token) {",
                        "    pm.collectionVariables.set('access_token', j.access_token);",
                        "    pm.environment.set('access_token', j.access_token);",
                        "  }",
                        "  if (j.refresh_token) {",
                        "    pm.collectionVariables.set('refresh_token', j.refresh_token);",
                        "    pm.environment.set('refresh_token', j.refresh_token);",
                        "  }",
                        "} catch (e) {}",
                    ],
                },
            }
        ],
    }


def build_environment(name: str, values: dict[str, str]) -> dict:
    return {
        "id": name.lower().replace(" ", "-"),
        "name": name,
        "values": [
            {"key": k, "value": v, "type": "default", "enabled": True}
            for k, v in values.items()
        ],
        "_postman_variable_scope": "environment",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=f"{DEFAULT_PROD}/openapi.json")
    parser.add_argument("--openapi", type=Path, default=None)
    parser.add_argument("--base-url", default=DEFAULT_PROD)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    openapi = load_openapi(args.url, args.openapi)
    (OUT_DIR / "openapi.prod.json").write_text(
        json.dumps(openapi, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    collection = build_collection(openapi, args.base_url)
    coll_path = OUT_DIR / "epoint-crm-api.postman_collection.json"
    coll_path.write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")

    prod_env = build_environment(
        "ePoint CRM — Production",
        {
            "baseUrl": DEFAULT_PROD,
            "access_token": "",
            "refresh_token": "",
            "bootstrap_admin_token": "",
        },
    )
    staging_env = build_environment(
        "ePoint CRM — Staging",
        {
            "baseUrl": DEFAULT_STAGING,
            "access_token": "",
            "refresh_token": "",
            "bootstrap_admin_token": "",
        },
    )
    (OUT_DIR / "epoint-crm.production.postman_environment.json").write_text(
        json.dumps(prod_env, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "epoint-crm.staging.postman_environment.json").write_text(
        json.dumps(staging_env, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    n_paths = len(openapi.get("paths") or {})
    n_items = sum(len(f["item"]) for f in collection["item"])
    print(f"OpenAPI paths: {n_paths}")
    print(f"Postman requests: {n_items}")
    print(f"Wrote {coll_path}")
    print(f"Wrote environments in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
