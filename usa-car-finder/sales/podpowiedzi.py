"""Co powiedzieć nowemu klientowi — gotowe zdania, nie nazwy pól.

`qualification._braki()` wie, CZEGO nie wiemy o kliencie. To jednak lista pól
(„budżet pod drzwi w złotówkach"), a broker w rozmowie potrzebuje ZDANIA. Ta
różnica nie jest kosmetyczna: pytanie o zgodę na auto po szkodzie to najtrudniejsze
i najbardziej kosztowne zdanie w całej tej sprzedaży — źle postawione zamyka
rozmowę, a odmowa klienta jest według `sales/gate.py` najczęstszą przyczyną
utraty leada.

DWIE FORMY, BO TO DWA RÓŻNE KANAŁY. Przez telefon zdanie może być dłuższe
i zawierać powód; w wiadomości ma być krótkie, bo długi tekst na WhatsAppie
zostaje bez odpowiedzi. Treść merytoryczna jest ta sama.

CZEGO TU NIE MA I BYĆ NIE MOŻE: obietnicy naprawy. Auto przyjeżdża w stanie
z aukcji, a naprawę możemy najwyżej wstępnie wycenić — tak mówi oferta i tak
muszą mówić te podpowiedzi, inaczej broker obieca coś, czego produkt nie robi.
Liczby też są prawdziwe: transport morski trwa 3-6 tygodni zależnie od stanu
(`ZALOZENIA_APLIKACJI.md`), a nie „miesiąc", bo klient to potem rozliczy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Podpowiedz:
    """Jedno pytanie do zadania, w dwóch formach, z uzasadnieniem."""

    klucz: str
    #: Krótka nazwa tematu — nagłówek w panelu.
    temat: str
    #: Co powiedzieć przez telefon. Pełne zdanie, z powodem.
    przez_telefon: str
    #: Co napisać. Krótsze, bo długi tekst zostaje bez odpowiedzi.
    na_pismie: str
    #: Dlaczego to pytanie jest ważne — dla brokera, nie dla klienta.
    dlaczego: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "klucz": self.klucz,
            "temat": self.temat,
            "przez_telefon": self.przez_telefon,
            "na_pismie": self.na_pismie,
            "dlaczego": self.dlaczego,
        }


#: Kolejność ma znaczenie: rozmowa telefoniczna ma ograniczoną uwagę, więc
#: najpierw pytania, które mogą ją zakończyć (szkoda, budżet), a dopiero potem
#: doprecyzowujące. Klucze zgadzają się z `qualification._braki()`.
PODPOWIEDZI: dict[str, Podpowiedz] = {
    "damage_ok": Podpowiedz(
        klucz="damage_ok",
        temat="Zgoda na auto po szkodzie",
        przez_telefon=(
            "Auta z aukcji w USA są w większości po szkodzie i stąd bierze się różnica "
            "w cenie. Auto przyjeżdża w takim stanie, w jakim stoi na aukcji, a naprawę "
            "rozliczamy osobno i mogę ją wstępnie wycenić, zanim cokolwiek Pan zdecyduje. "
            "Czy taki wariant Pana interesuje, czy szuka Pan wyłącznie auta bez szkód?"
        ),
        na_pismie=(
            "Auta z aukcji w USA są zwykle po szkodzie i dlatego są tańsze. Naprawa jest "
            "osobno, mogę ją wstępnie wycenić. Czy taki wariant Pana interesuje?"
        ),
        dlaczego=(
            "Najczęstsza przyczyna utraty klienta. Bez tej odpowiedzi szukanie nie ma sensu, "
            "bo połowa wyników to auta po szkodzie."
        ),
    ),
    "budzet": Podpowiedz(
        klucz="budzet",
        temat="Budżet pod drzwi",
        przez_telefon=(
            "Jaką kwotą Pan dysponuje na auto pod drzwi w Polsce, czyli razem z transportem, "
            "cłem, akcyzą i moją prowizją? Podaję zawsze jedną kwotę końcową i nie ma po "
            "drodze dopłat."
        ),
        na_pismie=(
            "Jaki ma Pan budżet na auto pod drzwi w Polsce? To kwota razem z transportem, "
            "cłem i wszystkimi opłatami, bez dopłat po drodze."
        ),
        dlaczego=(
            "Klient myśli kwotą końcową, nie ceną na aukcji. Sufit licytacji wyliczamy z niej "
            "osobno dla każdego auta, bo zależy od stanu USA."
        ),
    ),
    "marka_model": Podpowiedz(
        klucz="marka_model",
        temat="Marka i model",
        przez_telefon=(
            "Jakie auto ma Pan na myśli? Wystarczy marka i model, a jeśli waha się Pan między "
            "kilkoma, proszę wymienić wszystkie. Sprawdzę, które z nich realnie chodzą "
            "w tym budżecie."
        ),
        na_pismie="Jakie auto Pana interesuje? Marka i model, może być kilka do porównania.",
        dlaczego="Bez tego nie ma czego szukać. Kilka modeli daje większą szansę na trafienie w budżet.",
    ),
    "rocznik": Podpowiedz(
        klucz="rocznik",
        temat="Rocznik",
        przez_telefon=(
            "Od którego rocznika w górę szukamy? Rocznik rusza cenę najmocniej ze wszystkiego, "
            "więc warto ustalić widełki, zamiast szukać po całym rynku."
        ),
        na_pismie="Od którego rocznika szukamy? To najmocniej wpływa na cenę.",
        dlaczego="Najsilniejszy pojedynczy czynnik ceny. Bez widełek wyniki są przypadkowe.",
    ),
    "termin": Podpowiedz(
        klucz="termin",
        temat="Na kiedy",
        przez_telefon=(
            "Na kiedy potrzebuje Pan tego auta? Pytam, bo sam transport morski to trzy do "
            "sześciu tygodni, zależnie od stanu, w którym auto stoi, a do tego dochodzi "
            "odprawa. Jeśli termin jest napięty, poszukam bliżej wschodniego wybrzeża."
        ),
        na_pismie=(
            "Na kiedy potrzebuje Pan auta? Sam transport morski to 3-6 tygodni zależnie od "
            "stanu, więc przy pilnym terminie szukam bliżej wschodniego wybrzeża."
        ),
        dlaczego=(
            "Termin przesuwa wybór stanu USA, a stan przesuwa koszt transportu, który wchodzi "
            "do podstawy cła."
        ),
    ),
    "telefon": Podpowiedz(
        klucz="telefon",
        temat="Numer telefonu",
        przez_telefon=(
            "Na jaki numer mogę wysyłać propozycje? Zdjęcia i raporty idą WhatsAppem, więc "
            "najlepiej ten, który ma Pan w telefonie."
        ),
        na_pismie="Na jaki numer mogę wysłać propozycje? Zdjęcia i raporty idą WhatsAppem.",
        dlaczego="Cała dalsza obsługa idzie WhatsAppem. Bez numeru zostaje mail, który klienci czytają rzadziej.",
    ),
}


def dla_brakow(klucze: list[str]) -> list[dict[str, Any]]:
    """Podpowiedzi dla wskazanych braków, w kolejności ważności rozmowy."""
    return [PODPOWIEDZI[k].as_dict() for k in PODPOWIEDZI if k in klucze]
