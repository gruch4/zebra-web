<p align="center">
  <img src="docs/assets/logo.svg" width="112" height="112" alt="zebra-web logo">
</p>

<h1 align="center">zebra-web</h1>

<p align="center">
  <b>Self-hosted web UI for Zebra label printers.</b><br>
  Design, preview and print ZPL labels from your browser: no driver, no desktop software, and
  your label data never leaves your network.
</p>

<p align="center">
  <a href="https://github.com/gruch4/zebra-web/actions/workflows/ci.yml"><img src="https://github.com/gruch4/zebra-web/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/gruch4/zebra-web/actions/workflows/codeql.yml"><img src="https://github.com/gruch4/zebra-web/actions/workflows/codeql.yml/badge.svg" alt="CodeQL"></a>
  <a href="https://scorecard.dev/viewer/?uri=github.com/gruch4/zebra-web"><img src="https://api.scorecard.dev/projects/github.com/gruch4/zebra-web/badge" alt="OpenSSF Scorecard"></a>
  <a href="https://github.com/gruch4/zebra-web/releases/latest"><img src="https://img.shields.io/github/v/release/gruch4/zebra-web" alt="Latest release"></a>
  <a href="https://github.com/gruch4/zebra-web/pkgs/container/zebra-web"><img src="https://img.shields.io/badge/image-ghcr.io%2Fgruch4%2Fzebra--web-2496ed?logo=docker&logoColor=white" alt="Container image"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/gruch4/zebra-web" alt="MIT License"></a>
</p>

<p align="center">
  <img src="docs/screenshots/designer.png" alt="The label designer with a text field and a QR code on a 100 × 50 mm label" width="900">
</p>

zebra-web talks to Zebra label printers (tested with the **ZD420** series) over the network on the
raw ZPL port 9100. It runs as a single Docker container next to PostgreSQL. Use it to design labels
visually, paste ZPL from other software, mass-print from spreadsheets and let other systems print
through a REST API.

## Highlights

- **Visual label designer:** text, Code 128/39, EAN, UPC, ITF, QR, Data Matrix, PDF417, boxes,
  lines, ellipses and images/logos, with undo/redo, grid and snapping, layers and template
  variables.
- **Accurate local preview:** a built-in ZPL renderer draws every label on your server; nothing
  is sent to an online service. Its output has been [checked against real
  printouts](docs/print-results.md), and anything it cannot draw is listed under the preview.
- **Templates and mass printing:** put `{{variables}}` in any field, then print one label from a
  generated form, or one label per row of a CSV, TSV, JSON, YAML or XLSX file.
- **Label archive and print history:** saved labels with thumbnails, tags and `.zpl`
  import/export; every job with preview, reprint and "save as label".
- **Printer management:** several printers, live status, settings (width, darkness, speed, media,
  print mode…), calibration and other actions, and control over printer settings embedded in
  labels from other software.
- **REST API** with per-system tokens and OpenAPI docs, so other systems can print or store labels.
- **Optional login** with OpenID Connect (step-by-step guide for Authentik).
- **Self-contained:** one container, no telemetry, no external calls apart from your printers and
  your identity provider.

## Screenshots

<table>
  <tr>
    <td width="50%"><a href="docs/screenshots/printzpl.png"><img src="docs/screenshots/printzpl.png" alt="Print ZPL page"></a><br><b>Print ZPL:</b> paste ZPL, see a live preview, fill variables and print.</td>
    <td width="50%"><a href="docs/screenshots/designer-zpl.png"><img src="docs/screenshots/designer-zpl.png" alt="Designer showing the generated ZPL"></a><br><b>Designer:</b> the ZPL generated from the design.</td>
  </tr>
  <tr>
    <td><a href="docs/screenshots/designer-preview.png"><img src="docs/screenshots/designer-preview.png" alt="Designer showing the rendered preview"></a><br><b>Designer:</b> the generated ZPL drawn by the local renderer.</td>
    <td><a href="docs/screenshots/archive.png"><img src="docs/screenshots/archive.png" alt="Labels archive"></a><br><b>Labels archive:</b> saved labels and designs with thumbnails.</td>
  </tr>
  <tr>
    <td><a href="docs/screenshots/history.png"><img src="docs/screenshots/history.png" alt="Print history"></a><br><b>Print history:</b> every job, filterable, with reprint.</td>
    <td><a href="docs/screenshots/printers.png"><img src="docs/screenshots/printers.png" alt="Printers list"></a><br><b>Printers:</b> several printers with live status.</td>
  </tr>
  <tr>
    <td><a href="docs/screenshots/zebraprinter.png"><img src="docs/screenshots/zebraprinter.png" alt="Printer settings page"></a><br><b>Printer settings:</b> media, darkness, speed, calibration and all SGD settings.</td>
    <td><a href="docs/screenshots/api.png"><img src="docs/screenshots/api.png" alt="API access page"></a><br><b>API access:</b> tokens for other systems.</td>
  </tr>
</table>

## Quick start (Docker)

You need Docker with the Compose plugin, and a Zebra printer reachable over the network (or the
emulator, see below).

```bash
mkdir zebra-web && cd zebra-web
curl -fsSLO https://raw.githubusercontent.com/gruch4/zebra-web/main/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/gruch4/zebra-web/main/.env.example -o .env
# edit .env: at least POSTGRES_PASSWORD and PUBLIC_URL, and the login settings if you want them
docker compose up -d
```

Open <http://localhost:8000>, go to **Printers → Add printer**, enter the printer's IP address
and press *Test connection* (this fills in the model and resolution). If you set
`DEFAULT_PRINTER_HOST` in `.env`, that printer is created automatically on first start.

> [!WARNING]
> Login is **off** by default (`AUTH_ENABLED=false`). Then everyone who can open the web UI can
> print, change printer settings and create API tokens. Keep it on a trusted network, or turn on
> [login](#login-with-openid-connect) before exposing it, and put it behind an HTTPS reverse proxy.

**Try it without a printer:** start the bundled printer emulator and add a printer with host
`printer-emulator`, port `9100`:

```bash
docker compose --profile dev up -d
```

**Build from source** instead of pulling the image:

```bash
git clone https://github.com/gruch4/zebra-web.git && cd zebra-web
cp .env.example .env
make up        # or: make up-dev, which also starts the emulator
```

The image is a single container: FastAPI serves the API and the built React app. Database
migrations (Alembic) run automatically when it starts.

### Image tags and updates

Images are published to `ghcr.io/gruch4/zebra-web` for `linux/amd64` and `linux/arm64`:

| Tag | Contents |
|---|---|
| `latest` | the newest release |
| `1.2.3`, `1.2`, `1` | a release, or the newest release of a minor / major version |
| `edge` | the current `main` branch (may break) |
| `sha-abc1234` | one commit of `main` |

Choose the tag with `ZEBRA_WEB_TAG` in `.env` and update with
`docker compose pull && docker compose up -d`. Release notes are on the
[releases page](https://github.com/gruch4/zebra-web/releases). Each image comes with a build
provenance attestation: `gh attestation verify oci://ghcr.io/gruch4/zebra-web:latest -R gruch4/zebra-web`.

Back up the `db-data` volume (or `pg_dump` the database) before upgrading.

## Login with OpenID Connect

Authentication is optional (`AUTH_ENABLED=false` by default). The backend uses OpenID Connect and
has been tested with [Authentik](https://goauthentik.io/). To protect the UI with Authentik:

1. In Authentik, create an **OAuth2/OpenID Provider**:
   - Client type: *Confidential*
   - Redirect URI: `https://<your-zebra-web-host>/auth/callback`
   - Scopes: `openid`, `email`, `profile`
   - (optional) add a groups scope mapping if you want to restrict access by group
2. Create an **Application** that uses this provider and note its slug.
3. Set in `.env`:

   ```env
   AUTH_ENABLED=true
   PUBLIC_URL=https://<your-zebra-web-host>
   SESSION_SECRET=<output of: openssl rand -hex 32>
   OIDC_ISSUER=https://<authentik-host>/application/o/<application-slug>/
   OIDC_CLIENT_ID=<client id>
   OIDC_CLIENT_SECRET=<client secret>
   OIDC_ALLOWED_GROUPS=          # optional, e.g. "label-printing,admins"
   ```

The backend runs the authorization-code flow (with PKCE) and keeps the session in a signed,
HTTP-only cookie. Logging out also ends the Authentik session. The logged-in user is recorded
on saved labels and print jobs.

## Configuration

All settings are environment variables; see [`.env.example`](.env.example) for the full list.

| Variable | Default | Meaning |
|---|---|---|
| `ZEBRA_WEB_TAG` | `latest` | Image tag used by `docker-compose.yml` (see [Image tags](#image-tags-and-updates)) |
| `DATABASE_URL` | set by compose | `postgresql+asyncpg://user:pass@host:5432/db` |
| `PUBLIC_URL` | `http://localhost:8000` | External URL (OIDC redirect, secure cookies) |
| `FORWARDED_ALLOW_IPS` | `*` | Proxies whose `X-Forwarded-*` headers are trusted. `*` trusts every client, which is only right when the app can be reached through your reverse proxy alone; otherwise set it to the proxy's address |
| `PRINTER_TIMEOUT` | `5` | Seconds to wait for a printer |
| `PRINTER_ALLOWED_PORTS` | `6101,9100-9109` | TCP ports printers may use (comma-separated, ranges allowed). Loopback, link-local (e.g. cloud metadata) and other special addresses are always refused, so printer settings cannot be used to reach other services |
| `PRINTER_ALLOW_LOOPBACK` | `false` | Allow printers on `127.0.0.1` / `::1`, e.g. the emulator from `make emulator` (`make dev-backend` sets it) |
| `DEFAULT_PRINTER_HOST` | – | Create this printer on first start |
| `AUTH_ENABLED` | `false` | Require login with OpenID Connect |
| `BATCH_CHUNK_SIZE` | `50` | Labels sent per TCP connection when mass printing |
| `MAX_BATCH_ROWS` | `10000` | Row limit of a data file |
| `ENABLE_INTERNAL_DOCS` | `false` | Serve Swagger/ReDoc and the OpenAPI spec of the web UI's own API at `/docs`, `/redoc`, `/openapi.json` (the external API's docs are always on) |

## Templates and mass printing

Any text or barcode field (or raw ZPL) can contain `{{variable}}` placeholders. `{{date}}`,
`{{time}}`, `{{datetime}}` and `{{year}}` are filled in automatically. In the designer's
*Variables* tab you can give each variable a label, a default value, a type (text, number,
date) and mark it required. These settings drive the form on the *Print from template* page.

For mass printing, the first row (CSV/TSV/XLSX) or the object keys (JSON/YAML) are the column
names. They are matched to variables by name, and you can change the mapping or use a fixed
value for a variable. An optional `copies` column sets the number of copies per row. Rows with
errors are highlighted and skipped. A *dry run* downloads the generated ZPL instead of
printing. Each label is grouped under its batch in the print history. A batch stops if the
printer reports paper out, head open or ribbon out, and *Retry unprinted rows* continues it
later.

## External API

Other systems (for example a home-inventory app) can send ZPL to zebra-web, either to **print
it** or to **store it as a label** for later printing. Everything they create shows up for all
users: stored labels in the *Labels archive* (tagged `api`), prints in the *Print history*
(source *API*, attributed to the token's name and the user who created it).

- **Documentation:** Swagger UI at `/api/v1/docs`, the OpenAPI document at
  `/api/v1/openapi.json` (use it to generate a client). Both are readable without logging in and
  work offline.
- **Tokens:** open **API access** in the web UI, press *Create token*, give it a name (one per
  system) and optionally an expiry date, and copy the secret - it is shown only once and only a
  hash is stored. Revoke a token at any time; it stops working immediately. You manage your own
  tokens; tokens created while `AUTH_ENABLED=false` can be managed by every logged-in user (and
  with `AUTH_ENABLED=false` you manage all tokens, since there are no separate users).
- **Requests** send the token as `Authorization: Bearer zw_...`. The API always needs a token,
  even with `AUTH_ENABLED=false`. Note that in that mode anyone who can open the web UI can
  create tokens, so it does not protect anything. Use HTTPS in production, since the token
  travels in a header.

```bash
TOKEN=zw_...
HOST=http://localhost:8000

# which printers exist
curl -H "Authorization: Bearer $TOKEN" $HOST/api/v1/printers

# print ZPL ({{variables}} are filled in; the default printer is used unless printer_id is given)
curl -X POST $HOST/api/v1/print \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Idempotency-Key: item-42-2026-10-19" \
  -d '{"zpl": "^XA^FO50,50^A0N,40,40^FD{{name}}^FS^XZ", "variables": {"name": "Screws"}, "copies": 2}'

# store ZPL in the archive without printing; the same external_ref updates the label
curl -X POST $HOST/api/v1/labels \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "Screws M4", "zpl": "^XA^FD{{name}}^FS^XZ", "external_ref": "inventory:item-42"}'

# print a stored label by id
curl -X POST $HOST/api/v1/labels/12/print \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"variables": {"name": "Screws"}}'
```

Things to know when integrating:

- Printing is synchronous: the request returns when the printer has accepted the data. That is
  normally well under a second, but with an offline or busy printer it can take 10 seconds or
  more (prints to one printer queue up behind each other), so use an HTTP timeout of 30 s or
  more. If the printer is offline the job is still recorded (status *failed*) and the response
  is **`502`** with that job in the body.
- Send an `Idempotency-Key` header on print requests you may retry:
  - Already printed with that key (same token): you get the original job back (header
    `Idempotent-Replay: true`) instead of a second print.
  - Printer unreachable (nothing was sent): the key stays free, so the retry really prints.
  - Failure *after* the data was sent (the job's error says the printer may still print it): the
    key is kept and returns that failed job again, because the label may come out. Check the
    printer, and use a new key to print again.
  - Same key while that request is still printing: waits a few seconds for it, then `409` with
    `Retry-After`. Same key for a different request: `409`.
- `date`, `time`, `datetime` and `year` are built-in variables filled from the server's clock;
  sending a value for one is a `422` instead of being silently ignored. Use another name for
  your own dates.
- `external_ref` is your own id for a stored label. It is unique per token **owner**, not per
  token, so all systems whose tokens belong to the same person (or any systems when
  `AUTH_ENABLED=false`) share one namespace: prefix it with your system's name. Sending it again
  updates that label: fields you leave out keep their value, but edits made to the label's
  content in the web UI are overwritten.
- `GET /api/v1/labels` lists labels without their ZPL (it can be large); `GET /api/v1/labels/{id}`
  returns it. `created_by` is only filled for things made through the API (`api:<token name>`);
  web users' names and e-mail addresses are not exposed.
- `GET /api/v1/jobs/{id}` only returns jobs made through the API.
- There is no CORS: call the API from your server, not from browser JavaScript on another origin.

### Security notes

- A token is a standing credential. It keeps working if its creator is removed from the identity
  provider or from `OIDC_ALLOWED_GROUPS`, and tokens created while `AUTH_ENABLED=false` keep
  working after you enable login (they show as *Shared* on the **API access** page, and every
  logged-in user may revoke them). Review and revoke tokens when people leave or when you turn on
  login.
- When a token's owner can no longer log in, an operator can revoke their tokens from the server:

  ```bash
  docker compose exec app python -m app.token_admin list
  docker compose exec app python -m app.token_admin revoke 3 4          # by id
  docker compose exec app python -m app.token_admin revoke-owner <sub>  # all of one owner's
  ```

- With `AUTH_ENABLED=false` anyone who can open the web UI can create tokens, so token
  authentication adds no protection in that mode.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Printer notes

- Communication is plain TCP on port 9100. Printing sends ZPL; status uses `~HS`,
  identification uses `~HI`, and settings are read with `! U1 getvar "allcv"`.
- Settings are written with ZPL commands (`^PW ^LL ~SD ^PR ^MN ^MT ^MM ~TA ^LT ^LS ^PO`) and
  saved permanently with `^JUS`. Lengths are shown in millimetres and speed in mm/s; the app
  converts them to dots and inches per second for the printer.
- **Printer settings inside labels.** Label software (e.g. ZebraDesigner) puts printer settings
  into the ZPL. For each printer you choose, per group, whether the label's values or the
  printer's own settings are used (Printers → printer → *Printer settings inside labels*):

  | Group | Commands | Default |
  |---|---|---|
  | Media type and tracking | `^MN ^MT ^ML` | from label |
  | Darkness and print speed | `~SD ^MD ^PR` | from label |
  | Label position and orientation | `^LT ^LS ~TA ^PO` | from label |
  | Print mode (tear-off, peel, cutter) and backfeed | `^MM ~JS ^XB` | from printer |

  Commands that change the printer permanently or perform actions (`^JUS`, calibration, reset,
  cancel, configuration labels, network settings) are never sent. Settings a label does send
  stay active on the printer until another label or the settings page changes them.
- Calibration (`~JC`) feeds a few labels. Run it after changing the media type.
- Text uses `^CI28` (UTF-8), so national characters such as Polish ones print correctly with
  the printer's scalable font.
- The Print ZPL page keeps your last ZPL on the server, per user, so it is there again on
  your next visit, on any device.

## Preview accuracy

The preview comes from zebra-web's own ZPL renderer, so it can only be as good as its knowledge
of how printers really behave. The test labels in [`docs/print-tests/`](docs/print-tests/) cover
the places where the ZPL documentation leaves things open (font metrics, rotation, field blocks,
bar code layout, sticky state…), and [`docs/print-results.md`](docs/print-results.md) shows the
preview next to scans of the real printouts, round by round. The renderer covers the common ZPL
commands; fonts and some barcode details are approximations, and anything it cannot draw is
listed under the preview.

Printed the test labels on another model or firmware? Results are very welcome, see
[CONTRIBUTING.md](CONTRIBUTING.md#renderer-and-printer-behaviour).

## Development

Requirements: Python 3.14 + [uv](https://docs.astral.sh/uv/), Node.js 24, PostgreSQL (e.g. in
Docker).

```bash
make install

# PostgreSQL for the app and the tests
docker run -d --name zebra-web-db -p 5432:5432 \
  -e POSTGRES_USER=zebra -e POSTGRES_PASSWORD=zebra -e POSTGRES_DB=zebra postgres:18-alpine
docker exec zebra-web-db createdb -U zebra zebra_test

# backend on :8000
export DATABASE_URL=postgresql+asyncpg://zebra:zebra@localhost:5432/zebra
make dev-backend

# frontend on :5173 with /api and /auth proxied to :8000
make dev-frontend

# optional: fake printer on 127.0.0.1:9100 (dev-backend allows loopback printers for it)
make emulator
```

### Tests, linting and formatting

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://zebra:zebra@localhost:5432/zebra_test
make lint      # ruff check + ruff format --check, eslint, prettier --check, tsc
make test      # pytest (needs TEST_DATABASE_URL; the schema is created via Alembic) + vitest
make format    # apply ruff and prettier fixes
```

Backend tests run against a real PostgreSQL database and an in-process printer emulator.
Frontend tests use Vitest, Testing Library and MSW.

### Project layout

```
backend/            FastAPI app (uv project)
  app/api/          REST endpoints of the web UI (/api/...)
  app/api_v1/       external, token-authenticated API (/api/v1/...) with its own OpenAPI + Swagger
  app/printer/      TCP client, ~HS/~HI/SGD parsers, settings → ZPL, emulator
  app/render/       local ZPL → PNG renderer (lexer, renderer, barcodes, bundled fonts)
  app/zpl/          designer → ZPL generator, templating, graphics (^GF), data-file parsing
  app/services/     printing and background mass printing
  alembic/          database migrations
frontend/           React + TypeScript + Mantine (Vite)
  src/pages/        one component per page
  src/designer/     canvas (react-konva), store with undo/redo, property panels
docs/               print tests, print results, screenshots
.github/workflows/  CI, releases + image publishing, CodeQL, Scorecard, container scanning
```

### Continuous integration and releases

Every pull request runs the backend and frontend checks, builds the Docker image, and is checked
by CodeQL, dependency review and a pull request title check. Dependabot keeps dependencies,
base images and actions up to date.

Releases are automated with [release-please](https://github.com/googleapis/release-please): it
keeps a release pull request open that bumps the version and updates
[`CHANGELOG.md`](CHANGELOG.md) from the Conventional Commit messages on `main`. Merging it tags the
release, creates the GitHub Release and publishes the image. Every push to `main` also publishes
the `edge` image.

## Contributing

Contributions are welcome: bug reports, printer test results, docs and code. Please read
[CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md). For questions,
use [Discussions](https://github.com/gruch4/zebra-web/discussions).

## License

zebra-web is released under the [MIT License](LICENSE).

It bundles third-party components under their own licenses:
[DejaVu Sans Mono](backend/app/render/fonts/DejaVu-LICENSE.txt) (Bitstream Vera license),
[Roboto Condensed](backend/app/render/fonts/RobotoCondensed-OFL.txt) (SIL Open Font License 1.1)
and [Swagger UI](backend/app/api_v1/swagger/LICENSE) (Apache License 2.0).

Zebra, ZPL and ZebraDesigner are trademarks of Zebra Technologies Corporation. zebra-web is an
independent project and is not affiliated with, endorsed by or sponsored by Zebra Technologies.
