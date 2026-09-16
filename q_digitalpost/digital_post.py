"""Offentlig funktion til bestilling af Digital Post."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from automation_server_client import AutomationServer
from q_sharepoint_api.functionality.sp_documents import (
    delete_document,
    upload_document,
)

from q_digitalpost.configuration import (
    DIGITAL_POST_QUEUE_ID,
    MAX_DOCUMENT_SIZE_BYTES,
    MAX_TOTAL_SIZE_BYTES,
    SHAREPOINT_LIBRARY_NAME,
    SHAREPOINT_SITE_NAME,
)
from q_digitalpost.models import (
    DigitalPostAttachment,
    DigitalPostResult,
)


class DigitalPost:
    """Validerer og opretter bestillinger til Digital Post-køen."""

    async def send_digital_post(
        self,
        *,
        pdf_content: bytes,
        file_name: str,
        cpr_or_cvr: str,
        subject: str,
        source_process: str,
        source_item_id: str | int,
        attachments: list[DigitalPostAttachment] | None = None,
    ) -> DigitalPostResult:
        """
        Gemmer PDF-filerne og opretter et item i Digital Post-køen.

        Output:
            DigitalPostResult med:

            - forsendelses_id
            - queue_id
            - document_count
            - status="QUEUED"

        QUEUED betyder:
            - Input er valideret.
            - Alle PDF-filer er uploadet til SharePoint.
            - ATS-itemet er oprettet.

        QUEUED betyder ikke, at brevet allerede er leveret.
        """
        validated = self._validate_request(
            pdf_content=pdf_content,
            file_name=file_name,
            cpr_or_cvr=cpr_or_cvr,
            subject=subject,
            source_process=source_process,
            source_item_id=source_item_id,
            attachments=attachments or [],
        )

        self._validate_queue_id()

        forsendelses_id = str(uuid4())
        uploaded_documents: list[dict[str, Any]] = []

        status_message = "Klar til afsendelse"

        # Bruges til at afgøre, om SharePoint-filerne må slettes
        # i tilfælde af en efterfølgende fejl.
        queue_item_created = False

        try:
            # ----------------------------------------------------
            # UPLOAD HOVEDDOKUMENT OG BILAG
            # ----------------------------------------------------
            for document in validated["documents"]:
                dokument_id = str(uuid4())

                uploaded = await asyncio.to_thread(
                    upload_document,
                    site_name=SHAREPOINT_SITE_NAME,
                    library_name=SHAREPOINT_LIBRARY_NAME,
                    file_name=f"{dokument_id}.pdf",
                    content=document["content"],
                    fields={
                        "dokument_id": dokument_id,
                        "forsendelses_id": forsendelses_id,
                    },
                    conflict_behavior="fail",
                )

                drive_item_id = uploaded.get("drive_item_id")
                list_item_id = uploaded.get("list_item_id")

                if not drive_item_id or not list_item_id:
                    raise RuntimeError(
                        "SharePoint-uploaden mangler drive_item_id "
                        "eller list_item_id."
                    )

                uploaded_documents.append(
                    {
                        "dokument_id": dokument_id,
                        "file_name": document["file_name"],
                        "role": document["role"],
                        "drive_item_id": drive_item_id,
                        "list_item_id": str(list_item_id),
                        "size_bytes": len(document["content"]),
                    }
                )

            # ----------------------------------------------------
            # OPBYG ITEM-DATA
            # ----------------------------------------------------
            item_data = self._build_item_data(
                forsendelses_id=forsendelses_id,
                recipient_id=validated["recipient_id"],
                recipient_id_type=validated["recipient_id_type"],
                subject=validated["subject"],
                source_process=validated["source_process"],
                source_item_id=validated["source_item_id"],
                documents=uploaded_documents,
                status_message=status_message,
            )

            # ----------------------------------------------------
            # OPRET ATS-ITEM
            # ----------------------------------------------------
            workqueue = self._get_digital_post_workqueue()

            created_item = workqueue.add_item(
                data=item_data,
                reference=forsendelses_id,
            )

            queue_item_created = True

            # ----------------------------------------------------
            # SÆT MESSAGE PÅ DET OPRETTEDE ITEM
            # ----------------------------------------------------
            # Status forbliver NEW.
            # update_status() bruges kun til at sætte Message.
            try:
                created_item.update_status(
                    status="new",
                    message=status_message,
                )
            except Exception:
                # Itemet er allerede oprettet, og dokumenterne ligger
                # på SharePoint. En fejl i den synlige Message må derfor
                # ikke medføre, at dokumenterne slettes.
                logging.getLogger(__name__).warning(
                    "ATS-itemet blev oprettet, men Message kunne ikke "
                    "sættes. forsendelses_id=%s",
                    forsendelses_id,
                    exc_info=True,
                )

        except Exception:
            # SharePoint-filerne må kun slettes, hvis der endnu ikke
            # er oprettet et kø-item, som forventer at kunne hente dem.
            if not queue_item_created:
                await self._delete_uploaded_documents(
                    uploaded_documents
                )

            raise

        return DigitalPostResult(
            forsendelses_id=forsendelses_id,
            queue_id=DIGITAL_POST_QUEUE_ID,
            document_count=len(uploaded_documents),
            status="QUEUED",
    )

    def _get_digital_post_workqueue(self):
        """
        Opretter et Workqueue-objekt med Digital Post-køens faste ID.

        Output:
            Et Workqueue-objekt, som kan kalde add_item().
        """
        ats = AutomationServer.from_environment()
        environment_workqueue = ats.workqueue()

        if environment_workqueue is None:
            raise RuntimeError(
                "Automation Server returnerede ingen workqueue. "
                "Angiv ATS_WORKQUEUE_OVERRIDE i .env."
            )

        if hasattr(environment_workqueue, "model_copy"):
            workqueue = environment_workqueue.model_copy(
                update={"id": DIGITAL_POST_QUEUE_ID},
                deep=False,
            )
        elif hasattr(environment_workqueue, "copy"):
            workqueue = environment_workqueue.copy(
                update={"id": DIGITAL_POST_QUEUE_ID},
                deep=False,
            )
        else:
            raise TypeError(
                "Workqueue-objektet kan ikke kopieres med et nyt ID."
            )

        if workqueue.id is None or int(workqueue.id) != DIGITAL_POST_QUEUE_ID:
            raise RuntimeError(
                "Workqueue-objektet fik ikke det forventede queue-ID."
            )

        return workqueue

    async def _delete_uploaded_documents(
        self,
        uploaded_documents: list[dict[str, Any]],
    ) -> None:
        """
        Forsøger at slette filer efter en delvist fejlet bestilling.

        Output:
            None. Oprydningsfejl overskriver ikke den oprindelige fejl.
        """
        for document in uploaded_documents:
            drive_item_id = document.get("drive_item_id")
            if not drive_item_id:
                continue

            try:
                await asyncio.to_thread(
                    delete_document,
                    site_name=SHAREPOINT_SITE_NAME,
                    library_name=SHAREPOINT_LIBRARY_NAME,
                    drive_item_id=drive_item_id,
                )
            except Exception:
                # Eventuelle efterladte filer håndteres af cleanup-jobbet.
                pass

    @staticmethod
    def _build_item_data(
        *,
        forsendelses_id: str,
        recipient_id: str,
        recipient_id_type: str,
        subject: str,
        source_process: str,
        source_item_id: str,
        documents: list[dict[str, Any]],
        status_message: str,
    ) -> dict[str, Any]:
        """
        Bygger JSON-data til ATS-itemet.

        Output:
            Dictionary med box, defer, state og status. status_code
            indeholder samme tekst som workitemets Message.
        """
        created_at = datetime.now(
            ZoneInfo("Europe/Copenhagen")
        ).isoformat()

        return {
            "box": {
                "forsendelses_id": forsendelses_id,
                "recipient": {
                    "id": recipient_id,
                    "id_type": recipient_id_type,
                },
                "subject": subject,
                "source_process": source_process,
                "source_item_id": source_item_id,
                "documents": documents,
                "processing_state": "READY_TO_SEND",
                "serviceplatform_submission_id": None,
                "digital_post_id": None,
                "actual_delivery": None,
                "submitted_at": None,
                "completed_at": None,
                "last_error": None,
                "created_at": created_at,
            },
            "defer": None,
            "state": [f"Digital Post bestilt {created_at}"],
            "status": {
                "status": "New",
                "status_code": status_message,
            },
        }

    @staticmethod
    def _validate_request(
        *,
        pdf_content: bytes,
        file_name: str,
        cpr_or_cvr: str,
        subject: str,
        source_process: str,
        source_item_id: str | int,
        attachments: list[DigitalPostAttachment],
    ) -> dict[str, Any]:
        """
        Validerer hele bestillingen før første SharePoint-upload.

        Output:
            Normaliseret dictionary med modtager og dokumenter.
        """
        main_document = DigitalPost._validate_pdf(
            content=pdf_content,
            file_name=file_name,
            role="MAIN",
        )

        if not isinstance(attachments, list):
            raise TypeError("attachments skal være en liste.")

        documents = [main_document]
        file_names = {main_document["file_name"].casefold()}

        for attachment in attachments:
            if not isinstance(attachment, DigitalPostAttachment):
                raise TypeError(
                    "Alle bilag skal være DigitalPostAttachment-objekter."
                )

            validated_attachment = DigitalPost._validate_pdf(
                content=attachment.content,
                file_name=attachment.file_name,
                role="ATTACHMENT",
            )

            normalized_name = validated_attachment["file_name"].casefold()
            if normalized_name in file_names:
                raise ValueError(
                    "Hoveddokument og bilag skal have forskellige filnavne."
                )

            file_names.add(normalized_name)
            documents.append(validated_attachment)

        total_size = sum(len(document["content"]) for document in documents)
        if total_size > MAX_TOTAL_SIZE_BYTES:
            raise ValueError(
                f"Forsendelsens samlede størrelse er {total_size} bytes. "
                f"Maksimum er {MAX_TOTAL_SIZE_BYTES} bytes."
            )

        if not isinstance(cpr_or_cvr, str):
            raise TypeError("cpr_or_cvr skal være tekst.")

        recipient_id = re.sub(r"\D", "", cpr_or_cvr)
        if len(recipient_id) == 10:
            recipient_id_type = "CPR"
        elif len(recipient_id) == 8:
            recipient_id_type = "CVR"
        else:
            raise ValueError(
                "cpr_or_cvr skal indeholde 10 cifre for CPR "
                "eller 8 cifre for CVR."
            )

        return {
            "recipient_id": recipient_id,
            "recipient_id_type": recipient_id_type,
            "subject": DigitalPost._require_text(subject, "subject"),
            "source_process": DigitalPost._require_text(
                source_process,
                "source_process",
            ),
            "source_item_id": DigitalPost._require_text(
                str(source_item_id),
                "source_item_id",
            ),
            "documents": documents,
        }

    @staticmethod
    def _validate_pdf(
        *,
        content: bytes,
        file_name: str,
        role: str,
    ) -> dict[str, Any]:
        """
        Validerer én PDF.

        Output:
            Dictionary med content, file_name og role.
        """
        if not isinstance(content, bytes):
            raise TypeError(f"{role}: content skal være bytes.")
        if not content:
            raise ValueError(f"{role}: PDF-indholdet er tomt.")
        if not content.startswith(b"%PDF-"):
            raise ValueError(f"{role}: dokumentet er ikke en PDF.")
        if len(content) > MAX_DOCUMENT_SIZE_BYTES:
            raise ValueError(
                f"{role}: dokumentet er større end "
                f"{MAX_DOCUMENT_SIZE_BYTES} bytes."
            )

        validated_file_name = DigitalPost._require_text(
            file_name,
            "file_name",
        )
        if Path(validated_file_name).name != validated_file_name:
            raise ValueError("file_name må ikke indeholde en sti.")
        if not validated_file_name.lower().endswith(".pdf"):
            raise ValueError("Alle dokumenter skal have filendelsen .pdf.")

        return {
            "content": content,
            "file_name": validated_file_name,
            "role": role,
        }

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        """
        Validerer et obligatorisk tekstfelt.

        Output:
            Renset tekst uden mellemrum før og efter.
        """
        if not isinstance(value, str):
            raise TypeError(f"{field_name} skal være tekst.")

        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{field_name} må ikke være tom.")

        return cleaned

    @staticmethod
    def _validate_queue_id() -> None:
        """
        Kontrollerer queue-ID'et i configuration.py.

        Output:
            None, når ID'et er gyldigt.
        """
        if isinstance(DIGITAL_POST_QUEUE_ID, bool):
            raise TypeError("DIGITAL_POST_QUEUE_ID må ikke være bool.")
        if not isinstance(DIGITAL_POST_QUEUE_ID, int):
            raise TypeError("DIGITAL_POST_QUEUE_ID skal være et helt tal.")
        if DIGITAL_POST_QUEUE_ID <= 0:
            raise ValueError(
                "Indsæt Digital Post-køens tekniske ID i "
                "q_digitalpost/configuration.py."
            )
