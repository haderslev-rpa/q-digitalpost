"""Datamodeller til q-digitalpost."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DigitalPostAttachment:
    """
    Ét PDF-bilag til en Digital Post-forsendelse.

    Felter:
        content: PDF-filens indhold som bytes.
        file_name: Det filnavn modtageren skal se.
    """

    content: bytes
    file_name: str


@dataclass(frozen=True)
class DigitalPostResult:
    """
    Resultatet fra send_digital_post().

    Felter:
        forsendelses_id: Haderslevs UUID for hele forsendelsen.
        queue_id: Det tekniske ID på Digital Post-køen.
        document_count: Antal uploadede PDF-filer.
        status: QUEUED, når dokumenterne er gemt og itemet oprettet.
    """

    forsendelses_id: str
    queue_id: int
    document_count: int
    status: str
