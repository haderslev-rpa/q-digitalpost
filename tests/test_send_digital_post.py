"""
Integrationstest af q-digitalpost.

Læg Robot test.pdf i samme tests-mappe.
Ret DIGITAL_POST_QUEUE_ID i q_digitalpost/configuration.py først.

Kør:
    uv run python tests/test_send_digital_post.py

Testen opretter et rigtigt ATS-item og efterlader PDF'en i SharePoint.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from pprint import pprint

from q_digitalpost.digital_post import DigitalPost
from q_digitalpost.models import DigitalPostAttachment


TEST_PDF_NAME = "Robot test.pdf"
TEST_CPR_OR_CVR = "12345678"


async def main() -> None:
    """
    Opretter en testforsendelse med hoveddokument og ét bilag.

    Output:
        Printer DigitalPostResult fra send_digital_post().
    """
    pdf_path = Path(__file__).resolve().parent / TEST_PDF_NAME

    if not pdf_path.is_file():
        raise FileNotFoundError(
            f"Testfilen blev ikke fundet: {pdf_path}"
        )

    pdf_content = pdf_path.read_bytes()
    digital_post = DigitalPost()

    result = await digital_post.send_digital_post(
        pdf_content=pdf_content,
        file_name="Robot test.pdf",
        cpr_or_cvr=TEST_CPR_OR_CVR,
        subject="Test af q-digitalpost",
        source_process="q-digitalpost-integrationstest",
        source_item_id="lokal-test-1",
        attachments=[
            DigitalPostAttachment(
                content=pdf_content,
                file_name="Robot test bilag.pdf",
            )
        ],
    )

    pprint(result)
    print("")
    print("Forsendelsen er uploadet og lagt i ATS-køen.")
    print(f"forsendelses_id: {result.forsendelses_id}")


if __name__ == "__main__":
    asyncio.run(main())
