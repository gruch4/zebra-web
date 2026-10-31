"""Request and response models of the external API.

They are kept separate from the web UI's schemas so the public contract (and its OpenAPI
document) does not change when the UI's models do, and internal details such as printer
addresses stay out of it.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.zpl.templating import VariableDef

ZPL_MAX_LENGTH = 5_000_000


def _no_nul(value: str) -> str:
    # The database cannot store NUL characters; reject them up front with a clear error.
    if "\x00" in value:
        raise ValueError("must not contain NUL (\\x00) characters")
    return value


Text = Annotated[str, AfterValidator(_no_nul)]
Tag = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
    AfterValidator(_no_nul),
]

_ZPL_EXAMPLE = "^XA^FO50,50^A0N,40,40^FD{{name}}^FS^FO50,110^BCN,60,Y^FD{{sku}}^FS^XZ"


def public_creator(value: str | None) -> str | None:
    """Who made something, as shown to API clients: the integration (`api:<token name>`), never
    the e-mail address of a web user, and not the e-mail of a token's owner either."""
    if value and value.startswith("api:"):
        return value.rsplit(" (", 1)[0]
    return None


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PrintZplRequest(BaseModel):
    zpl: Text = Field(
        min_length=1,
        max_length=ZPL_MAX_LENGTH,
        description="The ZPL to print. `{{variable}}` placeholders are replaced from `variables`.",
    )
    name: Text | None = Field(
        None, max_length=200, description="A name for this print, shown in the print history."
    )
    variables: dict[Text, Text] = Field(
        default_factory=dict,
        description=(
            "Values for the `{{variable}}` placeholders in the ZPL. `date`, `time`, `datetime` "
            "and `year` are built in (filled with the current time) and cannot be set."
        ),
    )
    copies: int = Field(1, ge=1, le=1000, description="Number of copies of every label.")
    printer_id: int | None = Field(
        None, description="Printer to use (see `GET /printers`); the default printer if omitted."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "zpl": _ZPL_EXAMPLE,
                    "name": "Shelf label",
                    "variables": {"name": "Screws M4", "sku": "SCR-M4-100"},
                    "copies": 2,
                }
            ]
        }
    )


class PrintLabelRequest(BaseModel):
    variables: dict[Text, Text] = Field(
        default_factory=dict,
        description=(
            "Values for the label's variables. Variables with a default may be omitted. "
            "`date`, `time`, `datetime` and `year` are built in and cannot be set."
        ),
    )
    copies: int = Field(1, ge=1, le=1000, description="Number of copies of every label.")
    printer_id: int | None = Field(
        None, description="Printer to use (see `GET /printers`); the default printer if omitted."
    )

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"variables": {"sku": "SCR-M4-100"}, "copies": 1}]}
    )


class StoreLabelRequest(BaseModel):
    name: Text = Field(min_length=1, max_length=200, description="Name in the labels archive.")
    zpl: Text = Field(
        min_length=1,
        max_length=ZPL_MAX_LENGTH,
        description="The ZPL of the label; may contain `{{variable}}` placeholders.",
    )
    description: Text | None = None
    tags: list[Tag] | None = Field(
        None, max_length=20, description="Tags for the archive. The tag `api` is always added."
    )
    external_ref: Text | None = Field(
        None,
        min_length=1,
        max_length=255,
        description=(
            "Your own identifier for this label, e.g. an inventory item id. Sending the same "
            "`external_ref` again updates that label instead of creating another one. It is "
            "unique per token **owner**, not per token, so every system using the same owner's "
            "tokens shares one namespace: prefix it with your system's name."
        ),
    )
    width_mm: float | None = Field(None, gt=0, le=1000, description="Label width, for previews.")
    height_mm: float | None = Field(None, gt=0, le=4000, description="Label height, for previews.")
    dpi: int | None = Field(None, ge=100, le=600, description="Resolution; 203 if omitted.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Screws M4 shelf label",
                    "zpl": _ZPL_EXAMPLE,
                    "tags": ["inventory"],
                    "external_ref": "inventory:item-42",
                    "width_mm": 50,
                    "height_mm": 25,
                }
            ]
        }
    )


class ApiLabelSummary(ApiModel):
    """A label without its ZPL, as listed."""

    id: int
    name: str
    description: str
    kind: Literal["zpl", "design"] = Field(
        description="`design` labels were made in the web designer; their `zpl` is generated."
    )
    width_mm: float | None
    height_mm: float | None
    dpi: int
    tags: list[str]
    variables: list[VariableDef] = Field(description="The `{{variables}}` the label takes.")
    external_ref: str | None
    created_by: str | None = Field(
        description="`api:<token name>` for labels made through the API, otherwise null."
    )
    created_at: datetime
    updated_at: datetime

    _creator = field_validator("created_by")(public_creator)


class ApiLabel(ApiLabelSummary):
    zpl: str = Field(description="The ZPL, with its `{{variable}}` placeholders.")


class ApiLabelPage(BaseModel):
    items: list[ApiLabelSummary]
    total: int


class ApiPrinter(ApiModel):
    id: int
    name: str
    dpi: int
    model: str | None
    is_default: bool


class ApiPrintJob(ApiModel):
    id: int
    printer_id: int | None
    printer_name: str
    dpi: int
    label_id: int | None = Field(description="The archived label that was printed, if any.")
    label_name: str | None
    zpl: str = Field(description="The ZPL as sent to the printer.")
    variables: dict[str, str]
    copies: int
    status: Literal["sent", "failed"]
    error: str | None
    duration_ms: int | None
    created_by: str | None = Field(description="`api:<token name>`.")
    created_at: datetime

    _creator = field_validator("created_by")(public_creator)
