"""Datamodeller til q-digitalpost."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DeliveryMethod(StrEnum):
    """
    Angiver hvordan q-digitalpost må levere forsendelsen.

    ONLY_DIGITAL_POST:
        Forsendelsen må kun oprettes, når modtageren er
        tilmeldt Digital Post.

        Navn og fysisk adresse er ikke påkrævet.

        Hvis modtageren ikke er tilmeldt Digital Post,
        bliver der ikke uploadet dokumenter til SharePoint,
        og der bliver ikke oprettet et ATS-item.

    DIGITAL_OR_PHYSICAL_POST:
        Forsendelsen må leveres enten som Digital Post
        eller som fysisk post.

        Navn og fysisk adresse er påkrævet, fordi
        Serviceplatformen kan vælge fysisk post.
    """

    ONLY_DIGITAL_POST = "ONLY_DIGITAL_POST"
    DIGITAL_OR_PHYSICAL_POST = "DIGITAL_OR_PHYSICAL_POST"


@dataclass(frozen=True)
class DigitalPostAddress:
    """
    Modtagerens aktuelle navn og postadresse.

    Felter:
        name:
            Modtagerens aktuelle navn.

        street_name:
            Vejnavn eller vejadresseringsnavn.

        house_number:
            Husnummer inklusive eventuelt bogstav.

        postal_code:
            Postnummer.

        city:
            Postdistrikt eller bynavn.

        floor:
            Valgfri etage.

        door:
            Valgfri sidedør.

        co_name:
            Valgfrit c/o-navn.

        country_code:
            ISO-landekode. Standard er DK.

    Adresse kan med fordel dannes fra resultatet af:

        DatafordelerClient.get_aktuel_navn_og_adresse(...)
    """

    name: str
    street_name: str
    house_number: str
    postal_code: str
    city: str
    floor: str = ""
    door: str = ""
    co_name: str = ""
    country_code: str = "DK"

    @classmethod
    def from_datafordeler(
        cls,
        person_data: dict,
    ) -> DigitalPostAddress:
        """
        Danner en DigitalPostAddress fra Datafordeleren.

        Input:
            Resultatet fra:

            DatafordelerClient.get_aktuel_navn_og_adresse(...)

        Output:
            Et DigitalPostAddress-objekt.

        Bemærk:
            Den kaldende proces bør først kontrollere:

            person_data["kan_sendes_brev"]

            Hvis værdien er False, findes forklaringen i:

            person_data["kan_sendes_brev_aarsag"]
        """

        if not isinstance(person_data, dict):
            raise TypeError(
                "person_data skal være en dictionary."
            )

        return cls(
            name=str(
                person_data.get("navn") or ""
            ).strip(),
            street_name=str(
                person_data.get("vejadresseringsnavn")
                or person_data.get("vejnavn")
                or ""
            ).strip(),
            house_number=str(
                person_data.get("husnummer") or ""
            ).strip(),
            postal_code=str(
                person_data.get("postnummer") or ""
            ).strip(),
            city=str(
                person_data.get("postdistrikt")
                or person_data.get("bynavn")
                or ""
            ).strip(),
            floor=str(
                person_data.get("etage") or ""
            ).strip(),
            door=str(
                person_data.get("sidedoer") or ""
            ).strip(),
            country_code="DK",
        )


@dataclass(frozen=True)
class DigitalPostAttachment:
    """
    Ét PDF-bilag til en Digital Post-forsendelse.

    Felter:
        content:
            PDF-filens indhold som bytes.

        file_name:
            Det filnavn modtageren skal se.
    """

    content: bytes
    file_name: str


@dataclass(frozen=True)
class DigitalPostResult:
    """
    Resultatet fra send_digital_post().

    Felter:
        forsendelses_id:
            Haderslevs UUID for hele forsendelsen.

            Værdien er None, hvis intet blev oprettet.

        queue_id:
            Det tekniske ID på Digital Post-køen.

            Værdien er None, hvis intet blev oprettet.

        document_count:
            Antal uploadede PDF-filer.

        status:
            QUEUED:
                Dokumenterne er gemt, og ATS-itemet er oprettet.

            NOT_SENT:
                Der blev bevidst ikke oprettet en forsendelse.

        reason:
            Maskinlæsbar forklaring.

            Eksempel:
            RECIPIENT_NOT_REGISTERED_FOR_DIGITAL_POST

        message:
            Læsbar forklaring til den kaldende proces.
    """

    forsendelses_id: str | None
    queue_id: int | None
    document_count: int
    status: str
    reason: str = ""
    message: str = ""