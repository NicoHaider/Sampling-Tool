"""Unit: BDO-Gesellschaften + -Standorte (Single Source of Truth, Sprint 33)."""

from __future__ import annotations

from sampling_tool.io.bdo_locations import (
    BdoCompany,
    BdoLocation,
    companies,
    company_by_key,
    default_company,
    default_location,
    location_by_key,
    locations,
)


class TestLocations:
    def test_alle_neun_bundeslaender_vertreten(self) -> None:
        bundeslaender = {loc.bundesland for loc in locations()}
        assert bundeslaender == {
            "Wien",
            "Niederösterreich",
            "Burgenland",
            "Steiermark",
            "Kärnten",
            "Oberösterreich",
            "Salzburg",
            "Tirol",
            "Vorarlberg",
        }

    def test_default_location_ist_wien(self) -> None:
        assert default_location().key == "wien"
        assert default_location() is locations()[0]

    def test_location_by_key_findet_linz(self) -> None:
        linz = location_by_key("linz")
        assert linz is not None
        assert linz.display_name == "Linz"
        assert linz.bundesland == "Oberösterreich"
        assert linz.street == "Reuchlinstraße 6"
        assert linz.postal_code == "4020"
        assert linz.city == "Linz"
        assert linz.phone == "+43 5 70 375 4200"

    def test_location_by_key_unbekannt_ist_none(self) -> None:
        assert location_by_key("atlantis") is None

    def test_location_keys_eindeutig(self) -> None:
        keys = [loc.key for loc in locations()]
        assert len(keys) == len(set(keys))

    def test_locations_sind_bdo_location(self) -> None:
        assert all(isinstance(loc, BdoLocation) for loc in locations())


class TestCompanies:
    def test_default_company_ist_austria_gmbh(self) -> None:
        assert default_company().key == "austria_gmbh"
        assert default_company() is companies()[0]
        assert default_company().name.startswith("BDO Austria GmbH")

    def test_company_by_key_findet_consulting(self) -> None:
        company = company_by_key("consulting_gmbh")
        assert company is not None
        assert company.name == "BDO Consulting GmbH"

    def test_company_by_key_unbekannt_ist_none(self) -> None:
        assert company_by_key("nope") is None

    def test_company_keys_eindeutig(self) -> None:
        keys = [c.key for c in companies()]
        assert len(keys) == len(set(keys))

    def test_companies_sind_bdo_company(self) -> None:
        assert all(isinstance(c, BdoCompany) for c in companies())


class TestUnabhaengigkeit:
    """Kern der Sprint-33-Anforderung: Gesellschaft und Standort sind frei
    kombinierbar – kein company-Feld am Standort, kein location-Feld an der
    Gesellschaft."""

    def test_location_hat_kein_company_feld(self) -> None:
        assert not hasattr(default_location(), "company")

    def test_company_hat_nur_key_und_name(self) -> None:
        company = default_company()
        assert hasattr(company, "key")
        assert hasattr(company, "name")
        assert not hasattr(company, "bundesland")
