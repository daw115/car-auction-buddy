import os

os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "__all__")

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional


class CarLot(BaseModel):
    source: str                              # "copart" | "iaai" | "manheim"
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


class SearchTarget(BaseModel):
    """Jedna para marka+model do przeszukania.

    Klient rzadko podaje jeden model. W arkuszu leadów pada "karoq kodiaq, vw tiguan"
    — trzy modele z dwóch marek, które trzeba przeszukać razem i porównać w jednym
    rankingu. Pojedyncze pola make/model zostają jako cel podstawowy (pierwszy z listy),
    żeby nie przepisywać kilkunastu miejsc, które je czytają.
    """

    make: str
    model: Optional[str] = None

    @field_validator("make")
    @classmethod
    def make_not_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Marka celu wyszukiwania nie może być pusta")
        return cleaned


class ClientCriteria(BaseModel):
    make: str
    model: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    budget_usd: Optional[float] = None  # Opcjonalny — niektorzy klienci nie podaja
    max_odometer_mi: Optional[int] = None
    fuel_type: Optional[str] = None  # Gas / Hybrid / Diesel / Electric — server-side FUEL filter (Copart)
    allowed_damage_types: list[str] = Field(default_factory=list)
    excluded_damage_types: list[str] = Field(
        default_factory=lambda: ["Flood", "Fire"]
    )
    max_results: int = 15
    sources: list[str] = Field(default_factory=lambda: ["copart", "iaai"])

    # Dodatkowe cele wyszukiwania poza parą make/model. Pusta lista = szukamy tylko
    # celu podstawowego, czyli zachowanie sprzed wprowadzenia list.
    targets: list[SearchTarget] = Field(default_factory=list)

    # Segment nadwozia z pierwszej rozmowy ("suv"). NIE jest filtrem wyszukiwania —
    # Copart i IAAI szukają pełnotekstowo po marce i modelu, więc samo "suv" nie
    # zawęzi niczego sensownie. Służy agentowi do zaproponowania konkretnych modeli
    # w budżecie, gdy klient nie umie ich wskazać.
    segment: Optional[str] = None

    # Budżet "pod drzwi" w Polsce, tak jak podaje go klient ("50/60 tys").
    # Sufit ceny aukcyjnej wylicza scoring/budget.py, bo zależy od stanu USA.
    budget_pln_from: Optional[float] = None
    budget_pln_to: Optional[float] = None
    # Forma zakupu przesuwa sufit o ~1400 USD przy 50 tys. PLN, więc nie może być
    # założeniem — to pytanie do klienta.
    settlement: str = "private"

    @field_validator("make")
    @classmethod
    def make_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Marka jest wymagana")
        return value

    @field_validator("budget_usd")
    @classmethod
    def budget_positive(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("Budżet musi być większy od zera (lub null)")
        return value

    @field_validator("max_results")
    @classmethod
    def max_results_range(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_results musi być >= 1")
        # Cap do 15 (twardy limit z UI — chroni przed niepotrzebnym scrape'em długich list)
        return min(int(value), 15)

    @field_validator("sources")
    @classmethod
    def valid_sources(cls, value: list[str]) -> list[str]:
        allowed = {"copart", "iaai", "manheim"}
        normalized = [item.lower() for item in value]
        invalid = set(normalized) - allowed
        if invalid or not normalized:
            raise ValueError("sources musi zawierać copart, iaai lub manheim (co najmniej jedno)")
        return normalized

    @field_validator("fuel_type")
    @classmethod
    def normalize_fuel_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned.title()

    @field_validator("settlement")
    @classmethod
    def valid_settlement(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in {"private", "company"}:
            raise ValueError("settlement musi być 'private' albo 'company'")
        return normalized

    def search_targets(self) -> list[SearchTarget]:
        """Wszystkie pary marka+model do przeszukania, bez powtórzeń.

        Cel podstawowy zawsze pierwszy — od niego zależy kolejność, w jakiej
        scraper wyczerpuje budżet zapytań.
        """
        seen: set[tuple[str, Optional[str]]] = set()
        targets: list[SearchTarget] = []
        for candidate in [SearchTarget(make=self.make, model=self.model), *self.targets]:
            key = (candidate.make.strip().lower(), (candidate.model or "").strip().lower() or None)
            if key in seen:
                continue
            seen.add(key)
            targets.append(candidate)
        return targets

    def budget_pln(self) -> Optional[float]:
        """Górna granica budżetu — po niej liczymy sufit ceny aukcyjnej.

        Klient podaje widełki ("50/60 tys"), a szukamy do górnej: dolna mówi tylko,
        od czego zaczyna się rozmowa o cenie.
        """
        return self.budget_pln_to or self.budget_pln_from

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("Rocznik od nie może być większy niż rocznik do")
        if self.max_odometer_mi is not None and self.max_odometer_mi <= 0:
            raise ValueError("Przebieg musi być większy od zera")
        if (
            self.budget_pln_from
            and self.budget_pln_to
            and self.budget_pln_from > self.budget_pln_to
        ):
            raise ValueError("Budżet od nie może być większy niż budżet do")
        return self


class AIAnalysis(BaseModel):
    lot_id: str
    score: float = Field(ge=0, le=10)
    recommendation: str              # "POLECAM" | "RYZYKO" | "PONAD BUDŻET" | "ODRZUĆ"
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
    client_reports_html: list[str] = Field(default_factory=list)  # Lista URL-ów per-lot raportów dla klienta (POLECAM)
    broker_reports_html: list[str] = Field(default_factory=list)  # Lista URL-ów per-lot raportów brokerskich (POLECAM)
    # Per-lot mapping: lot_id -> {client_url, broker_url}
    # UI używa tego do per-row download buttons (po naszym hybrid LLM auto-generate)
    auto_reports_by_lot_id: dict[str, dict[str, str]] = Field(default_factory=dict)
    analysis_notice: Optional[str] = None
    collected_count: int = 0  # Ile lotów zebrano przed skróceniem odpowiedzi UI
    vin_coverage: dict[str, int] = Field(default_factory=dict)  # {"with_full_vin": N, "total": M}
    # True gdy wyszukiwanie nie znalazło żadnych lotów — UI może wtedy
    # zaproponować dodanie zapytania do kolejki ponownego sprawdzania.
    no_results: bool = False
