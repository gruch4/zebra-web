from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.zpl.generator import Design
from app.zpl.printer_settings import Source, resolve_policy
from app.zpl.templating import VariableDef

# What a web UI client may label a print as. "api" is set only by the external API, so the
# source can be trusted to mean "sent with an API token" in history and filters.
ClientJobSource = Literal["raw", "designer", "archive", "reprint", "template", "batch"]
JobSource = Literal["raw", "designer", "archive", "reprint", "template", "batch", "api"]


class Page[T](BaseModel):
    items: list[T]
    total: int


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _without_nul[T](data: T) -> T:
    """Refuse NUL characters anywhere in JSON-like input, keys included: Postgres takes them
    neither in text nor in JSONB, so saving or searching for them would fail with a 500."""
    pending: list[Any] = [data]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if "\x00" in item:
                raise ValueError("Text must not contain NUL (\\x00) characters")
        elif isinstance(item, dict):
            pending += item.keys()
            pending += item.values()
        elif isinstance(item, list):
            pending += item
    return data


class StoredIn(BaseModel):
    """Input that is saved to the database."""

    @model_validator(mode="before")
    @classmethod
    def _no_nul(cls, data: Any) -> Any:
        return _without_nul(data)


NoNulStr = Annotated[str, AfterValidator(_without_nul)]
VariableDefsIn = Annotated[list[VariableDef], BeforeValidator(_without_nul)]


# ---- printers -------------------------------------------------------------------------------


class PrinterIn(StoredIn):
    name: str = Field(min_length=1, max_length=200)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(9100, ge=1, le=65535)
    dpi: int = Field(203, ge=100, le=600)
    model: str | None = Field(None, max_length=100)
    firmware: str | None = Field(None, max_length=100)
    is_default: bool = False


class PrinterOut(ORMModel):
    id: int
    name: str
    host: str
    port: int
    dpi: int
    model: str | None
    firmware: str | None
    is_default: bool
    label_settings: dict[str, Source]
    created_at: datetime
    updated_at: datetime

    @field_validator("label_settings", mode="before")
    @classmethod
    def _with_defaults(cls, value: dict | None) -> dict[str, str]:
        return resolve_policy(value)


class LabelSettingsGroup(BaseModel):
    group: str
    title: str
    commands: list[str]
    default: Source


class ConnectionTest(BaseModel):
    host: str = Field(min_length=1)
    port: int = Field(9100, ge=1, le=65535)


class ConnectionTestResult(BaseModel):
    ok: bool
    model: str | None = None
    firmware: str | None = None
    dpi: int | None = None
    error: str | None = None


class PrinterStatusOut(BaseModel):
    online: bool
    ready: bool = False
    problems: list[str] = []
    error: str | None = None
    details: dict | None = None


class SettingOut(BaseModel):
    name: str
    label: str
    value: str | None
    choices: str | None


class PrinterSettingsOut(BaseModel):
    settings: list[SettingOut]
    info: dict[str, str | None]


class RawSetting(BaseModel):
    key: str
    value: str
    choices: str | None


class ActionOut(BaseModel):
    action: str
    description: str


# ---- printing -------------------------------------------------------------------------------


class PrintRequest(BaseModel):
    printer_id: int | None = None
    zpl: str | None = None
    label_id: int | None = None
    design: Design | None = None
    variables: dict[str, str] = {}
    # Defaults, required flags and types of the zpl or design variables; a label_id print
    # uses the label's stored definitions instead.
    definitions: list[VariableDef] = []
    copies: int = Field(1, ge=1, le=1000)
    source: ClientJobSource | None = None
    keep_printer_settings: bool = False

    @model_validator(mode="after")
    def _one_source(self) -> PrintRequest:
        given = [v for v in (self.zpl, self.label_id, self.design) if v is not None]
        if len(given) != 1:
            raise ValueError("Provide exactly one of zpl, label_id or design")
        return self


class PrintJobOut(ORMModel):
    id: int
    printer_id: int | None
    printer_name: str
    printer_host: str
    dpi: int
    label_id: int | None
    label_name: str | None
    source: str
    zpl: str
    variables: dict[str, str]
    copies: int
    status: str
    error: str | None
    duration_ms: int | None
    batch_id: int | None
    batch_row: int | None
    created_by: str | None
    created_at: datetime


class RenderRequest(BaseModel):
    zpl: str = Field(max_length=5_000_000)
    dpi: int = Field(203, ge=100, le=600)
    width_mm: float | None = Field(None, gt=0, le=1000)
    height_mm: float | None = Field(None, gt=0, le=4000)
    index: int = Field(0, ge=0)
    strip_printer_settings: bool = False
    printer_id: int | None = None  # whose label settings policy to apply when stripping
    # Values to fill the `{{variables}}` with, as printing does; when given, unfilled ones are
    # shown as written.
    variables: dict[str, str] | None = None


class RenderInfo(BaseModel):
    image: str  # data URL
    width: int
    height: int
    label_count: int
    warnings: list[str]


class VariablesRequest(BaseModel):
    zpl: str


class VariablesOut(BaseModel):
    variables: list[str]


# ---- labels ---------------------------------------------------------------------------------


class LabelIn(StoredIn):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    kind: Literal["zpl", "design"]
    zpl: str | None = None
    design: Design | None = None
    width_mm: float | None = Field(None, gt=0, le=1000)
    height_mm: float | None = Field(None, gt=0, le=4000)
    dpi: int = Field(203, ge=100, le=600)
    tags: list[str] = []
    variables: list[VariableDef] = []

    @model_validator(mode="after")
    def _content(self) -> LabelIn:
        if self.kind == "zpl" and not self.zpl:
            raise ValueError("zpl is required for kind 'zpl'")
        if self.kind == "design" and self.design is None:
            raise ValueError("design is required for kind 'design'")
        return self


class LabelUpdate(StoredIn):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    zpl: str | None = None
    design: Design | None = None
    width_mm: float | None = Field(None, gt=0, le=1000)
    height_mm: float | None = Field(None, gt=0, le=4000)
    dpi: int | None = Field(None, ge=100, le=600)
    tags: list[str] | None = None
    variables: list[VariableDef] | None = None


class LabelSummary(ORMModel):
    id: int
    name: str
    description: str
    kind: str
    width_mm: float | None
    height_mm: float | None
    dpi: int
    tags: list[str]
    variables: list[VariableDef]
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class LabelOut(LabelSummary):
    zpl: str
    design: Design | None


class TemplatePreviewRequest(BaseModel):
    variables: dict[str, str] = {}


# ---- batches --------------------------------------------------------------------------------


class ParsedRow(BaseModel):
    index: int
    values: dict[str, str]
    copies: int
    errors: list[str]


class ParseResult(BaseModel):
    format: str
    columns: list[str]
    rows: list[dict[str, str]]
    mapping: dict[str, str | None]
    copies_column: str | None
    preview: list[ParsedRow]
    valid_count: int
    error_count: int


class BatchRequest(StoredIn):
    label_id: int
    printer_id: int | None = None
    rows: list[dict[str, str]] = Field(min_length=1)
    mapping: dict[str, str | None] = {}
    constants: dict[str, str] = {}
    copies_column: str | None = None
    selected: list[int] | None = None
    data_filename: str = ""

    @field_validator("data_filename")
    @classmethod
    def _fit_filename(cls, value: str) -> str:
        return value[:255]


class BatchOut(ORMModel):
    id: int
    label_id: int | None
    label_name: str
    printer_id: int | None
    printer_name: str
    data_filename: str
    total: int
    sent: int
    failed: int
    status: str
    error: str | None
    created_by: str | None
    created_at: datetime
    finished_at: datetime | None


class DryRunOut(BaseModel):
    zpl: str
    count: int
    skipped: list[ParsedRow]


# ---- misc -----------------------------------------------------------------------------------


class UserOut(BaseModel):
    sub: str
    email: str | None = None
    name: str | None = None
    auth_enabled: bool


class ApiTokenIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00]*$")
    expires_at: AwareDatetime | None = None


class ApiTokenOut(BaseModel):
    id: int
    name: str
    prefix: str
    owner: str
    shared: bool  # created before login was enabled; every logged-in user may manage it
    status: Literal["active", "expired", "revoked"]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiTokenCreated(ApiTokenOut):
    token: str  # shown only once


class GraphicOut(BaseModel):
    width: int
    height: int
    bytes_per_row: int
    data: str  # base64 bitmap
    zpl: str
    preview: str  # data URL


class PrinterSettingsRequest(BaseModel):
    zpl: str = Field(max_length=5_000_000)
    printer_id: int | None = None


class EmbeddedSettingOut(BaseModel):
    command: str
    description: str
    group: str | None


class PrinterSettingsInZpl(BaseModel):
    zpl: str  # the ZPL as it will be sent
    removed: list[EmbeddedSettingOut]  # replaced by the printer's own settings
    kept: list[EmbeddedSettingOut]  # used from the label


class DraftIn(StoredIn):
    data: dict


class DraftOut(BaseModel):
    name: str
    data: dict
    updated_at: datetime | None
