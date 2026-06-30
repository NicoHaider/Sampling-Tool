"""BDO-Gesellschaften und -Standorte als Single Source of Truth (Sprint 33).

Gesellschaft (`BdoCompany`) und Standort (`BdoLocation`) sind bewusst
**voneinander unabhängige** Listen: jede Gesellschaft ist mit jedem Standort
frei kombinierbar (z. B. „BDO Consulting GmbH" am Standort Linz). Darum trägt
der Standort **kein** `company`-Feld und die Gesellschaft **kein** Standort-Feld.

Reine Daten + Lookups – **keine** Qt-/SQL-/I/O-Abhängigkeiten. Wer BDO-Adressen
oder -Gesellschaftsnamen braucht, holt sie hier; nirgends sonst hartkodieren.

Quelle: bdo.at/Standorte + Impressum (recherchiert 2026-06-29). Telefonnummern
im Website-Format ohne Bindestrich-Varianten. Für Lustenau (Straße) und Bruck an
der Leitha (Straße/PLZ) lagen keine zuverlässig verifizierten Adressdaten vor –
diese Felder bleiben leer; der Adressblock lässt leere Zeilen aus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class BdoLocation:
    """Ein BDO-Standort (rein ortsbezogen – ohne Gesellschaft)."""

    key: str
    display_name: str
    bundesland: str
    street: str
    postal_code: str
    city: str
    phone: str
    email: str


@dataclass(frozen=True, slots=True)
class BdoCompany:
    """Eine BDO-Gesellschaft (vollständiger rechtlicher Name)."""

    key: str
    name: str


# Standorte – alle neun Bundesländer. Reihenfolge = Dropdown-Reihenfolge,
# erster Eintrag (Wien) ist Default.
BDO_LOCATIONS: Final[tuple[BdoLocation, ...]] = (
    BdoLocation(
        key="wien",
        display_name="Wien",
        bundesland="Wien",
        street="QBC 4 – Am Belvedere 4, Eingang Karl-Popper-Straße 4",
        postal_code="1100",
        city="Wien",
        phone="+43 5 70 375 1000",
        email="wien@bdo.at",
    ),
    BdoLocation(
        key="graz",
        display_name="Graz",
        bundesland="Steiermark",
        street="Schubertstraße 62",
        postal_code="8010",
        city="Graz",
        phone="+43 5 70 375 8000",
        email="graz@bdo.at",
    ),
    BdoLocation(
        key="linz",
        display_name="Linz",
        bundesland="Oberösterreich",
        street="Reuchlinstraße 6",
        postal_code="4020",
        city="Linz",
        phone="+43 5 70 375 4200",
        email="linz@bdo.at",
    ),
    BdoLocation(
        key="salzburg",
        display_name="Salzburg",
        bundesland="Salzburg",
        street="Himmelreich 1",
        postal_code="5020",
        city="Salzburg",
        phone="+43 5 70 375 5000",
        email="salzburg@bdo.at",
    ),
    BdoLocation(
        key="innsbruck",
        display_name="Innsbruck",
        bundesland="Tirol",
        street="Neuhauserstraße 7",
        postal_code="6020",
        city="Innsbruck",
        phone="+43 5 70 375 6300",
        email="innsbruck@bdo.at",
    ),
    BdoLocation(
        key="klagenfurt",
        display_name="Klagenfurt am Wörthersee",
        bundesland="Kärnten",
        street="Stauderplatz 5, Top 28",
        postal_code="9020",
        city="Klagenfurt am Wörthersee",
        phone="+43 5 70 375 8900",
        email="klagenfurt@bdo.at",
    ),
    BdoLocation(
        key="eisenstadt",
        display_name="Eisenstadt",
        bundesland="Burgenland",
        street="Bankgasse 3",
        postal_code="7000",
        city="Eisenstadt",
        phone="+43 5 70 375 7700",
        email="eisenstadt@bdo.at",
    ),
    BdoLocation(
        key="lustenau",
        display_name="Lustenau",
        bundesland="Vorarlberg",
        street="",
        postal_code="6890",
        city="Lustenau",
        phone="+43 5 70 375",
        email="lustenau@bdo.at",
    ),
    BdoLocation(
        key="bruck_leitha",
        display_name="Bruck an der Leitha",
        bundesland="Niederösterreich",
        street="",
        postal_code="",
        city="Bruck an der Leitha",
        phone="+43 5 70 375",
        email="",
    ),
)


# Gesellschaften – unabhängige Liste, frei mit jedem Standort kombinierbar.
# Reihenfolge = Dropdown-Reihenfolge, erster Eintrag ist Default.
BDO_COMPANIES: Final[tuple[BdoCompany, ...]] = (
    BdoCompany(
        key="austria_gmbh",
        name="BDO Austria GmbH Wirtschaftsprüfungs- und Steuerberatungsgesellschaft",
    ),
    BdoCompany(
        key="assurance_gmbh",
        name="BDO Assurance GmbH Wirtschaftsprüfungs- und Steuerberatungsgesellschaft",
    ),
    BdoCompany(
        key="audit_gmbh",
        name="BDO Audit GmbH Wirtschaftsprüfungs- und Steuerberatungsgesellschaft",
    ),
    BdoCompany(
        key="gmbh",
        name="BDO GmbH Wirtschaftsprüfungs- und Steuerberatungsgesellschaft",
    ),
    BdoCompany(key="consulting_gmbh", name="BDO Consulting GmbH"),
    BdoCompany(key="corporate_finance_gmbh", name="BDO Corporate Finance GmbH"),
    BdoCompany(
        key="steiermark_gmbh",
        name="BDO Steiermark GmbH Wirtschaftsprüfungs und Steuerberatungsgesellschaft",
    ),
    BdoCompany(
        key="oberoesterreich_gmbh",
        name="BDO Oberösterreich GmbH Wirtschaftsprüfungs- und Steuerberatungsgesellschaft",
    ),
    BdoCompany(key="holding_gmbh", name="BDO Austria Holding Wirtschaftsprüfung GmbH"),
)


def locations() -> tuple[BdoLocation, ...]:
    """Alle Standorte (für das Standort-Dropdown)."""
    return BDO_LOCATIONS


def companies() -> tuple[BdoCompany, ...]:
    """Alle Gesellschaften (für das Gesellschafts-Dropdown)."""
    return BDO_COMPANIES


def location_by_key(key: str) -> BdoLocation | None:
    """Standort zum stabilen `key` oder `None`."""
    return next((loc for loc in BDO_LOCATIONS if loc.key == key), None)


def company_by_key(key: str) -> BdoCompany | None:
    """Gesellschaft zum stabilen `key` oder `None`."""
    return next((c for c in BDO_COMPANIES if c.key == key), None)


def default_location() -> BdoLocation:
    """Default-Standort (Wien, erster Eintrag)."""
    return BDO_LOCATIONS[0]


def default_company() -> BdoCompany:
    """Default-Gesellschaft (BDO Austria GmbH …, erster Eintrag)."""
    return BDO_COMPANIES[0]
