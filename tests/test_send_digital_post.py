"""
Integrationstest af q-digitalpost med adresseoplysninger.

Testen bruger fiktive modtageroplysninger og vælger:

    DIGITAL_OR_PHYSICAL_POST

Det betyder, at navn og adresse gemmes i ATS-itemet, så
worker-processen senere kan opbygge både Digital Post og
fysisk post.

Læg Robot test.pdf i samme tests-mappe.

Kontrollér først DIGITAL_POST_QUEUE_ID i:

    q_digitalpost/configuration.py

Kør:

    uv run python tests/test_send_digital_post.py

Testen:

1. Læser Robot test.pdf.
2. Validerer forsendelsen og den fiktive adresse.
3. Uploader hoveddokument og bilag til SharePoint.
4. Opretter et rigtigt item i Automation Server-køen.
5. Efterlader testfilerne i SharePoint.

Testen sender ikke brevet videre til Serviceplatformen.
Det sker først, når worker-processen behandler ATS-itemet.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from pprint import pprint

from q_digitalpost.digital_post import DigitalPost
from q_digitalpost.models import (
    DeliveryMethod,
    DigitalPostAddress,
    DigitalPostAttachment,
)


TEST_PDF_NAME = "Robot test.pdf"

# Der bruges et fiktivt CPR-nummer med korrekt format.
# Nummeret anvendes kun som testdata i ATS-itemet.
TEST_CPR_OR_CVR = "010190-1234"

# Fiktive adresseoplysninger.
TEST_ADDRESS = DigitalPostAddress(
    name="Test Testesen",
    street_name="Testvej",
    house_number="3",
    postal_code="6100",
    city="Haderslev",
    floor="2.",
    door="th",
    co_name="",
    country_code="DK",
)


async def main() -> None:
    """
    Opretter en testforsendelse med fysisk adresse.

    Output:
        Printer DigitalPostResult fra send_digital_post().

        Ved succes forventes:

            status = "QUEUED"
            queue_id = Digital Post-køens tekniske ID
            document_count = 2
            forsendelses_id = et nyt UUID

        Testen opretter et rigtigt ATS-item og uploader
        dokumenterne til SharePoint.
    """

    pdf_path = (
        Path(__file__).resolve().parent
        / TEST_PDF_NAME
    )

    if not pdf_path.is_file():
        raise FileNotFoundError(
            "Testfilen blev ikke fundet: "
            f"{pdf_path}"
        )

    pdf_content = pdf_path.read_bytes()

    digital_post = DigitalPost()

    result = await digital_post.send_digital_post(
        pdf_content=pdf_content,
        file_name="Robot test.pdf",
        cpr_or_cvr=TEST_CPR_OR_CVR,
        subject="Test af q-digitalpost med adresse",
        source_process=(
            "q-digitalpost-integrationstest"
        ),
        source_item_id=(
            "lokal-test-med-adresse-1"
        ),
        delivery_method=(
            DeliveryMethod.DIGITAL_OR_PHYSICAL_POST
        ),
        address=TEST_ADDRESS,
        attachments=[
            DigitalPostAttachment(
                content=pdf_content,
                file_name="Robot test bilag.pdf",
            )
        ],
    )

    print("")
    print("Resultat fra q-digitalpost:")
    pprint(result)

    print("")
    print("Kontrol af resultat:")

    if result.status != "QUEUED":
        raise RuntimeError(
            "Integrationstesten forventede status "
            f"QUEUED, men modtog {result.status}."
        )

    if not result.forsendelses_id:
        raise RuntimeError(
            "Integrationstesten modtog ikke et "
            "forsendelses_id."
        )

    if result.document_count != 2:
        raise RuntimeError(
            "Integrationstesten forventede 2 dokumenter, "
            f"men modtog {result.document_count}."
        )

    print("Forsendelsen er uploadet og lagt i ATS-køen.")
    print(
        "forsendelses_id: "
        f"{result.forsendelses_id}"
    )
    print(
        "queue_id: "
        f"{result.queue_id}"
    )
    print(
        "document_count: "
        f"{result.document_count}"
    )
    print(
        "delivery_method: "
        f"{DeliveryMethod.DIGITAL_OR_PHYSICAL_POST.value}"
    )
    print("Fiktiv adresse blev tilføjet til ATS-itemet.")
    print("")
    print(
        "Bemærk: Testen har ikke sendt brevet til "
        "Serviceplatformen."
    )


if __name__ == "__main__":
    asyncio.run(main())