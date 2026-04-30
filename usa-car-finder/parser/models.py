import os

os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "__all__")

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional


class CarLot(BaseModel):
    source: str                              # "copart" | "iaai"
    lot_id: str
    url: str
    html_file: Optional[str] = None

    # Dane podstawowe
    vin: Optional[str] = None
    full_vin: Optional[str] = None           # pełny VIN z rozszerzenia (Copart ukrywa ostatnie 6 znaków)
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    odometer_mi: Optional[int] = None
    odometer_km: Optional[int] = None

    # Uszkodzenia i tytuł
    damage_primary: Optional[str] = None
    damage_secondary: Optional[str] = None
    title_type: Optional[str] = None        # Clean / Salvage / Rebuilt / Parts Only / Flood

    # Ceny
    current_bid_usd: Optional[float] = None
    buy_now_price_usd: Optional[float] = None
    seller_reserve_usd: Optional[float] = None   # cena rezerwowa z rozszerzenia

    # Sprzedawca (z rozszerzenia AuctionGate/AutoHelperBot)
    seller_type: Optional[str] = None       # "insurance" | "dealer" | "unknown"

    # Lokalizacja
    location_state: Optional[str] = None
    location_city: Optional[str] = None

    # Aukcja
    auction_date: Optional[str] = None
    keys: Optional[bool] = None
    airbags_deployed: Optional[bool] = None

    # Media
    images: list[str] = Field(default_factory=list)

    # Metadane
    enriched_by_extension: bool = False
    delivery_cost_estimate_usd: Optional[float] = None
    raw_data: dict = Field(default_factory=dict)


class ClientCriteria(BaseModel):
    make: str
    model: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    budget_usd: float
    max_odometer_mi: Optional[int] = None
    allowed_damage_types: list[str] = Field(default_factory=list)
    excluded_damage_types: list[str] = Field(
        default_factory=lambda: ["Flood", "Fire"]
    )
    max_results: int = 30
    sources: list[str] = Field(default_factory=lambda: ["copart", "iaai"])

    @field_validator("make")
    @classmethod
    def make_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Marka jest wymagana")
        return value

    @field_validator("budget_usd")
    @classmethod
    def budget_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Budżet musi być większy od zera")
        return value

    @field_validator("max_results")
    @classmethod
    def max_results_range(cls, value: int) -> int:
        if value < 1 or value > 100:
            raise ValueError("max_results musi być w zakresie 1-100")
        return value

    @field_validator("sources")
    @classmethod
    def valid_sources(cls, value: list[str]) -> list[str]:
        allowed = {"copart", "iaai"}
        normalized = [item.lower() for item in value]
        invalid = set(normalized) - allowed
        if invalid or not normalized:
            raise ValueError("sources musi zawierać copart, iaai lub oba")
        return normalized

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("Rocznik od nie może być większy niż rocznik do")
        if self.max_odometer_mi is not None and self.max_odometer_mi <= 0:
            raise ValueError("Przebieg musi być większy od zera")
        return self


class AIAnalysis(BaseModel):
    lot_id: str
    score: float = Field(ge=0, le=10)
    recommendation: str              # "POLECAM" | "RYZYKO" | "ODRZUĆ"
    red_flags: list[str] = Field(default_factory=list)
    estimated_repair_usd: Optional[int] = None
    estimated_total_cost_usd: Optional[int] = None
    client_description_pl: str
    ai_notes: Optional[str] = None


class AnalyzedLot(BaseModel):
    lot: CarLot
    analysis: AIAnalysis
    is_top_recommendation: bool = False  # Czy lot jest w TOP 5
    included_in_report: bool = True  # Czy lot ma być w raporcie (edytowalne)


class SearchResponse(BaseModel):
    """Odpowiedź z wyszukiwania - TOP 5 + wszystkie pozostałe"""
    record_id: Optional[int] = None  # ID zapisanego rekordu klienta w SQLite
    client_id: Optional[int] = None  # ID klienta w SQLite
    top_recommendations: list[AnalyzedLot] = Field(default_factory=list)  # TOP 5 wybranych przez AI
    all_results: list[AnalyzedLot] = Field(default_factory=list)  # Wszystkie wyniki
    ai_input_file: Optional[str] = None  # Pełny JSON danych do AI
    ai_prompt_file: Optional[str] = None  # Gotowy prompt/plik do wklejenia w AI
    analysis_file: Optional[str] = None  # JSON z rankingiem i uzasadnieniem
    client_report_file: Optional[str] = None  # Markdown gotowy do wklejenia/wysłania
    artifact_urls: dict[str, str] = Field(default_factory=dict)  # Linki do pobrania artefaktów z UI
    analysis_notice: Optional[str] = None
    collected_count: int = 0  # Ile lotów zebrano przed skróceniem odpowiedzi UI
