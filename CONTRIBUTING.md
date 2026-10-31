# Contributing to zebra-web

Thanks for helping! Bug reports, printer test results, documentation fixes and code are all
welcome. zebra-web is maintained in spare time, so reviews and answers are best effort.

- **Questions and ideas:** use [Discussions](https://github.com/gruch4/zebra-web/discussions).
- **Bugs:** open an [issue](https://github.com/gruch4/zebra-web/issues/new/choose). For anything
  to do with printing, include the printer model, its firmware version and the ZPL.
- **Security problems:** report them privately, see [SECURITY.md](SECURITY.md).
- **Larger changes:** please open an issue or discussion first, so we can agree on the approach
  before you spend time on it.

## Development setup

Requirements: Python 3.14 + [uv](https://docs.astral.sh/uv/), Node.js 24, Docker (for
PostgreSQL), GNU Make.

```bash
make install

# PostgreSQL for the app and the tests
docker run -d --name zebra-web-db -p 5432:5432 \
  -e POSTGRES_USER=zebra -e POSTGRES_PASSWORD=zebra -e POSTGRES_DB=zebra postgres:18-alpine
docker exec zebra-web-db createdb -U zebra zebra_test

export DATABASE_URL=postgresql+asyncpg://zebra:zebra@localhost:5432/zebra
export TEST_DATABASE_URL=postgresql+asyncpg://zebra:zebra@localhost:5432/zebra_test

make dev-backend    # API on :8000
make dev-frontend   # UI on :5173, proxies /api and /auth to :8000
make emulator       # optional: fake printer on 127.0.0.1:9100
```

See [Development](README.md#development) in the README for more.

## Before you open a pull request

```bash
make format   # ruff + prettier fixes
make lint     # ruff, eslint, prettier --check, tsc
make test     # pytest (needs TEST_DATABASE_URL) + vitest
```

CI runs the same checks, and also builds the Docker image.

- Add or update tests for what you change. Backend tests run against a real PostgreSQL database
  and an in-process printer emulator; frontend tests use Vitest, Testing Library and MSW.
- Update the README when you change configuration, the API or behaviour users will notice.
- Keep pull requests focused: one change per pull request is easier to review and to release.

### Renderer and printer behaviour

The preview is only useful if it matches what printers really print, so changes to the renderer
(`backend/app/render/`) or to the generated ZPL should be backed by a printout where possible:

- [`docs/print-tests/`](docs/print-tests/) has test labels that cover the tricky parts of ZPL;
  `make_print_tests.py` writes them (edit the script, not the `.zpl` files).
- Say in the pull request which printer and firmware you checked on, and attach a photo or scan
  of the label next to the preview if the change affects what is drawn.

## Commit messages and pull request titles

Pull requests are squash-merged, and the **pull request title becomes the commit message**.
Releases are automated with [release-please](https://github.com/googleapis/release-please), which
reads those messages to choose the next version and write the changelog. Titles must therefore
follow [Conventional Commits](https://www.conventionalcommits.org/) (a CI check enforces this):

| Title | Release |
|---|---|
| `fix: …`, `fix(renderer): …` | patch (1.2.**3**) |
| `feat: …`, `feat(designer): …` | minor (1.**3**.0) |
| `feat!: …`, or a `BREAKING CHANGE:` footer | major (**2**.0.0) |
| `docs:`, `test:`, `refactor:`, `build:`, `ci:`, `chore:` | none on its own |

Use a scope when it helps, for example `renderer`, `designer`, `api`, `printer`, `templates`.

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE), like the rest of the project.
