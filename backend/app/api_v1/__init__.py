"""The external, token-authenticated API for other systems, mounted at /api/v1.

It is a separate FastAPI application so it has its own OpenAPI document (served at
/api/v1/openapi.json) and Swagger page (/api/v1/docs) that cover only these endpoints.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api_v1.routes import router

SWAGGER_DIR = Path(__file__).resolve().parent / "swagger"

DESCRIPTION = """
Send ZPL from another system to a Zebra printer, or store it in the labels archive for later.
Everything created through this API is visible to all users of the web UI: labels in the
**Labels archive**, prints in the **Print history** (source *API*).

## Authentication

Create a token in the web UI under **API access** (you can create several, one per system, and
revoke them at any time) and send it with every request:

```
Authorization: Bearer zw_...
```

The token is shown once, when it is created. A missing, unknown, expired or revoked token gets
`401`. Tokens are credentials: use HTTPS and keep them secret. A token keeps working even if
the person who created it later loses access to the web UI, so revoke tokens that are no longer
needed (an operator can also do it from the server, see the README).

## Printing

`POST /print` and `POST /labels/{label_id}/print` return once the printer has accepted the
data. That is normally well under a second, but if the printer is offline or busy it can take
10 seconds or more (prints to one printer queue up behind each other), so use a generous HTTP
timeout (30 s or more). If the printer cannot be reached, the job is still recorded in the
history with status `failed` and the response is **`502`** with that job in the body.

`{{variables}}` are filled from `variables`. The names `date`, `time`, `datetime` and `year`
are built in (the current time on the server) and cannot be set; sending one is a `422`.

### Retrying safely

Send an `Idempotency-Key` header (any unique string up to 255 characters, per request you may
retry):

- Already printed with this key: you get the original job back (`Idempotent-Replay: true`)
  and nothing is printed again.
- The printer could not be reached at all: the key stays free, so a retry really prints.
- The failure came *after* the data was sent (the job's `error` says the printer may still
  print it): the key is kept. The same key returns that failed job again, because the label
  may come out of the printer. Check it, and use a new key to print again.
- A request with the key is still being processed: `409` with `Retry-After`.
- The key was used for a different request: `409`.

## Storing labels

`POST /labels` saves ZPL in the archive without printing it. Add an `external_ref` (your own id,
e.g. `inventory:item-42`) to make it repeatable: the same `external_ref` updates the label
instead of creating a duplicate, and fields you leave out keep their value. Refs are unique per
token **owner**, not per token: systems whose tokens belong to the same person share one
namespace, so prefix refs with the system's name.

`GET /labels` lists labels without their ZPL; `GET /labels/{label_id}` returns it. `created_by`
is only filled for labels and jobs made through the API (as `api:<token name>`).
""".strip()

TAGS = [
    {"name": "Printing", "description": "Send labels to a printer."},
    {"name": "Labels", "description": "The labels archive."},
    {"name": "Printers", "description": "Available printers."},
]


def create_v1_app(parent: FastAPI) -> FastAPI:
    v1 = FastAPI(
        title="Zebra Web external API",
        version="1.0.0",
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url=None,
        redoc_url=None,
    )
    # Inside a mount `request.app` is this sub-application; share the parent's settings,
    # engine and session factory (set up in the parent's lifespan) with it.
    v1.state = parent.state
    v1.include_router(router)

    # Swagger UI is served from our own files so the page works without internet access.
    v1.mount("/swagger", StaticFiles(directory=SWAGGER_DIR), name="swagger")

    @v1.get("/docs", include_in_schema=False)
    async def swagger_ui(request: Request) -> HTMLResponse:
        root = request.scope.get("root_path", "").rstrip("/")
        return get_swagger_ui_html(
            openapi_url=f"{root}/openapi.json",
            title=f"{v1.title} - Swagger UI",
            swagger_js_url=f"{root}/swagger/swagger-ui-bundle.js",
            swagger_css_url=f"{root}/swagger/swagger-ui.css",
            swagger_favicon_url=f"{root}/swagger/favicon-32x32.png",
        )

    return v1
