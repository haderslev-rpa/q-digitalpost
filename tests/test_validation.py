"""Lokale valideringstests uden SharePoint og ATS-køoprettelse."""

from q_digitalpost.digital_post import DigitalPost
from q_digitalpost.models import DigitalPostAttachment


PDF_BYTES = b"%PDF-1.4\nTest"


def test_cpr() -> None:
    """Tester normalisering af CPR."""
    result = DigitalPost._validate_request(
        pdf_content=PDF_BYTES,
        file_name="brev.pdf",
        cpr_or_cvr="010190-1234",
        subject="Afgørelse",
        source_process="test-proces",
        source_item_id="12",
        attachments=[],
    )

    assert result["recipient_id_type"] == "CPR"
    assert result["recipient_id"] == "0101901234"


def test_cvr_og_bilag() -> None:
    """Tester normalisering af CVR og ét PDF-bilag."""
    result = DigitalPost._validate_request(
        pdf_content=PDF_BYTES,
        file_name="brev.pdf",
        cpr_or_cvr="12 34 56 78",
        subject="Brev",
        source_process="test-proces",
        source_item_id=12,
        attachments=[
            DigitalPostAttachment(
                content=PDF_BYTES,
                file_name="bilag.pdf",
            )
        ],
    )

    assert result["recipient_id_type"] == "CVR"
    assert result["recipient_id"] == "12345678"
    assert len(result["documents"]) == 2


if __name__ == "__main__":
    test_cpr()
    test_cvr_og_bilag()
    print("Alle valideringstests er bestået.")
