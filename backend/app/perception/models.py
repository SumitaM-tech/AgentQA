"""Typed observation models. `PageObservation` is the full, structured record
of what the agent perceived; `compact.py` turns it into a small prompt-ready form."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

PageLoadState = Literal["loading", "domcontentloaded", "load", "networkidle"]
StrategyKind = Literal["testid", "id", "role", "label", "placeholder", "text", "css"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BoundingBox(BaseModel):
    """Viewport-relative CSS pixels."""
    x: int
    y: int
    width: int
    height: int


class SelectorStrategy(BaseModel):
    """One way to re-find an element. Ordered from most to least semantic;
    `css` (structural path) is last-resort and flagged fragile."""
    kind: StrategyKind
    value: str
    role: str | None = None
    nth: int | None = None  # None => unique among candidates when observed
    fragile: bool = False


class PageElement(BaseModel):
    id: str = Field(description="Stable semantic id (e.g. 'e3fa91c', 'e3fa91c.2' for duplicates).")
    role: str
    tag: str
    name: str = ""  # computed accessible name
    text: str = ""
    aria_label: str | None = None
    placeholder: str | None = None
    value: str | None = None  # redacted for sensitive fields
    input_type: str | None = None
    href: str | None = None
    visible: bool = True
    in_viewport: bool = True
    enabled: bool = True
    checked: bool | None = None
    required: bool = False
    readonly: bool = False
    focused: bool = False
    bounding_box: BoundingBox | None = None
    selector_strategy: SelectorStrategy
    fallback_strategies: list[SelectorStrategy] = Field(default_factory=list)
    fingerprint: str = ""  # semantic fingerprint, re-verified before every action
    landmark: str | None = None
    context: str | None = None  # row-context hash; set only when it disambiguates duplicates


class Viewport(BaseModel):
    width: int
    height: int
    scroll_x: int = 0
    scroll_y: int = 0
    page_width: int = 0
    page_height: int = 0
    device_pixel_ratio: float = 1.0


class Heading(BaseModel):
    level: int
    text: str


class FormInfo(BaseModel):
    id: str | None = None
    method: str | None = None
    action: str | None = None
    field_count: int = 0


class DomMetadata(BaseModel):
    lang: str | None = None
    meta_description: str | None = None
    headings: list[Heading] = Field(default_factory=list)
    landmarks: dict[str, int] = Field(default_factory=dict)
    forms: list[FormInfo] = Field(default_factory=list)
    form_count: int = 0
    link_count: int = 0
    image_count: int = 0
    images_missing_alt: int = 0
    iframe_count: int = 0
    dom_node_count: int = 0
    interactive_total: int = 0
    interactive_hidden: int = 0
    open_dialog: bool = False


class ConsoleError(BaseModel):
    level: str = "error"
    text: str
    count: int = 1
    timestamp: datetime = Field(default_factory=utcnow)


class NetworkError(BaseModel):
    """Failed request or HTTP >= 400. Query strings are stripped."""
    url: str
    method: str
    status: int | None = None
    resource_type: str = "other"
    failure: str | None = None
    kind: Literal["http_error", "request_failed"] = "http_error"
    count: int = 1


class BrowserException(BaseModel):
    """Uncaught page exception / unhandled rejection."""
    message: str
    stack: str | None = None
    count: int = 1
    timestamp: datetime = Field(default_factory=utcnow)


class TruncationReport(BaseModel):
    elements_omitted: int = 0
    visible_text_omitted_chars: int = 0
    accessibility_tree_omitted_chars: int = 0
    console_errors_omitted: int = 0
    network_errors_omitted: int = 0

    @property
    def any(self) -> bool:
        return any(v > 0 for v in self.model_dump().values())


class PageObservation(BaseModel):
    observation_id: str = Field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = Field(default_factory=utcnow)
    url: str
    title: str
    screenshot_path: str | None = None
    accessibility_tree: str | None = None
    visible_text: str = ""
    interactive_elements: list[PageElement] = Field(default_factory=list)
    console_errors: list[ConsoleError] = Field(default_factory=list)
    network_errors: list[NetworkError] = Field(default_factory=list)
    browser_exceptions: list[BrowserException] = Field(default_factory=list)
    dialogs: list[str] = Field(default_factory=list)
    viewport: Viewport
    page_load_state: PageLoadState = "load"
    dom_metadata: DomMetadata = Field(default_factory=DomMetadata)
    state_fingerprint: str = ""  # url path + structure; for exploration-graph dedup
    truncation: TruncationReport = Field(default_factory=TruncationReport)
    warnings: list[str] = Field(default_factory=list)

    # Convenience wrappers (see compact.py)
    def to_prompt_text(self, options: Any = None) -> str:
        from app.perception.compact import to_prompt_text

        return to_prompt_text(self, options)

    def to_compact_dict(self, options: Any = None) -> dict[str, Any]:
        from app.perception.compact import to_compact_dict

        return to_compact_dict(self, options)


class ObservationLimits(BaseModel):
    """Everything that bounds the size of an observation."""
    max_elements: int = 150
    max_visible_text_chars: int = 4000
    max_accessibility_chars: int = 5000
    max_name_chars: int = 80
    max_value_chars: int = 80
    max_console_errors: int = 15
    max_network_errors: int = 15
    max_exceptions: int = 8
    max_message_chars: int = 300
    max_headings: int = 12
    redact_secrets: bool = True
    tag_dom: bool = True  # write data-agentqa-id attributes (fast path); false = strategies only
    include_accessibility: bool = True
    network_idle_probe_ms: int = 300
