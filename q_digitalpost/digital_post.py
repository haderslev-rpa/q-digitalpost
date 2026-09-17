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
    DeliveryMethod,
    DigitalPostAddress,
    DigitalPostAttachment,
    DigitalPostResult,
)

from q_serviceplatformen import (
    digital_post as serviceplatform_digital_post,
)
from q_serviceplatformen.functionality.access import (
    get_kombit_access,
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
        delivery_method: DeliveryMethod,
        attachments: list[DigitalPostAttachment] | None = None,
        address: DigitalPostAddress | None = None,
    ) -> DigitalPostResult:
        """
        Kontrollerer modtageren og opretter eventuelt en
        bestilling i Digital Post-køen.

        Input:
            pdf_content:
                Hoveddokumentets PDF-indhold som bytes.

            file_name:
                Det filnavn modtageren skal se.

            cpr_or_cvr:
                Modtagerens CPR- eller CVR-nummer.

            subject:
                Forsendelsens emne.

            source_process:
                Navnet på den proces, som bestiller forsendelsen.

            source_item_id:
                Processens egen reference til arbejdet.

            delivery_method:
                ONLY_DIGITAL_POST eller
                DIGITAL_OR_PHYSICAL_POST.

            attachments:
                Valgfri liste af PDF-bilag.

            address:
                Modtagerens aktuelle navn og adresse.

                Feltet er kun obligatorisk ved
                DIGITAL_OR_PHYSICAL_POST.

                Adressen kan med fordel dannes med:

                DigitalPostAddress.from_datafordeler(
                    person_data
                )

                hvor person_data kommer fra:

                DatafordelerClient
                    .get_aktuel_navn_og_adresse(...)

        Output:
            DigitalPostResult med status QUEUED, når dokumenterne
            er uploadet til SharePoint og ATS-itemet er oprettet.

            Ved ONLY_DIGITAL_POST og en modtager, som ikke er
            tilmeldt Digital Post, returneres status NOT_SENT.

            Ved NOT_SENT uploades ingen dokumenter, og der oprettes
            intet ATS-item.

        Fejl:
            En teknisk fejl under opslaget hos q-serviceplatformen
            rejses til den kaldende proces.

            En teknisk fejl må aldrig behandles som manglende
            tilmelding til Digital Post.
        """

        validated = self._validate_request(
            pdf_content=pdf_content,
            file_name=file_name,
            cpr_or_cvr=cpr_or_cvr,
            subject=subject,
            source_process=source_process,
            source_item_id=source_item_id,
            delivery_method=delivery_method,
            attachments=attachments or [],
            address=address,
        )

        # ----------------------------------------------------
        # SYNKRONT OPSLAG FØR SHAREPOINT OG ATS
        # ----------------------------------------------------
        if delivery_method == DeliveryMethod.ONLY_DIGITAL_POST:
            is_registered = await asyncio.to_thread(
                self._is_registered_for_digital_post,
                validated["recipient_id"],
            )

            if not isinstance(is_registered, bool):
                raise TypeError(
                    "Registreringsopslaget returnerede ikke "
                    "True eller False."
                )

            if not is_registered:
                return DigitalPostResult(
                    forsendelses_id=None,
                    queue_id=None,
                    document_count=0,
                    status="NOT_SENT",
                    reason=(
                        "RECIPIENT_NOT_REGISTERED_"
                        "FOR_DIGITAL_POST"
                    ),
                    message=(
                        "Der blev ikke sendt noget, fordi "
                        "modtageren ikke er tilmeldt Digital Post."
                    ),
                )


        self._validate_queue_id()

        forsendelses_id = str(uuid4())
        uploaded_documents: list[dict[str, Any]] = []
        status_message = "Klar til afsendelse"

        # Bruges til at afgøre, om SharePoint-filerne må slettes
        # i tilfælde af en efterfølgende fejl.
        queue_item_created = False

        try:
            # ------------------------------------------------
            # UPLOAD HOVEDDOKUMENT OG BILAG
            # ------------------------------------------------
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

                drive_item_id = uploaded.get(
                    "drive_item_id"
                )
                list_item_id = uploaded.get(
                    "list_item_id"
                )

                if not drive_item_id or not list_item_id:
                    raise RuntimeError(
                        "SharePoint-uploaden mangler "
                        "drive_item_id eller list_item_id."
                    )

                uploaded_documents.append(
                    {
                        "dokument_id": dokument_id,
                        "file_name": document["file_name"],
                        "role": document["role"],
                        "drive_item_id": drive_item_id,
                        "list_item_id": str(list_item_id),
                        "size_bytes": len(
                            document["content"]
                        ),
                    }
                )

            # ------------------------------------------------
            # OPBYG ITEM-DATA
            # ------------------------------------------------
            item_data = self._build_item_data(
                forsendelses_id=forsendelses_id,
                recipient_id=validated["recipient_id"],
                recipient_id_type=(
                    validated["recipient_id_type"]
                ),
                subject=validated["subject"],
                source_process=validated["source_process"],
                source_item_id=validated["source_item_id"],
                delivery_method=(
                    validated["delivery_method"]
                ),
                address=validated["address"],
                documents=uploaded_documents,
                status_message=status_message,
            )

            # ------------------------------------------------
            # OPRET ATS-ITEM
            # ------------------------------------------------
            workqueue = (
                self._get_digital_post_workqueue()
            )

            created_item = workqueue.add_item(
                data=item_data,
                reference=forsendelses_id,
            )

            queue_item_created = True

            # ------------------------------------------------
            # SÆT MESSAGE PÅ DET OPRETTEDE ITEM
            # ------------------------------------------------
            try:
                created_item.update_status(
                    status="new",
                    message=status_message,
                )
            except Exception:
                logging.getLogger(__name__).warning(
                    "ATS-itemet blev oprettet, men Message "
                    "kunne ikke sættes. forsendelses_id=%s",
                    forsendelses_id,
                    exc_info=True,
                )

        except Exception:
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
            reason="",
            message=(
                "Forsendelsen er uploadet og lagt "
                "i Digital Post-køen."
            ),
        )

    @staticmethod
    def _is_registered_for_digital_post(
        recipient_id: str,
    ) -> bool:
        """
        Kontrollerer synkront, om modtageren er tilmeldt
        Digital Post.

        Funktionen bruger q-serviceplatformens eksisterende
        registreringsopslag mod PostForespoerg.

        Input:
            recipient_id:
                Normaliseret CPR- eller CVR-nummer uden
                bindestreg, mellemrum eller andre skilletegn.

                CPR skal indeholde 10 cifre.
                CVR skal indeholde 8 cifre.

        Output:
            True:
                Opslaget blev gennemført, og modtageren er
                tilmeldt Digital Post.

            False:
                Opslaget blev gennemført, men modtageren er
                ikke tilmeldt Digital Post.

        Fejl:
            TypeError eller ValueError ved ugyldigt input.

            HTTP-, token-, certifikat- og autentificeringsfejl
            fra q-serviceplatformen sendes videre til den
            kaldende proces.

            Tekniske fejl bliver aldrig ændret til False.
        """

        if not isinstance(recipient_id, str):
            raise TypeError(
                "recipient_id skal være tekst."
            )

        normalized_recipient_id = re.sub(
            r"\D",
            "",
            recipient_id,
        )

        if len(normalized_recipient_id) not in (8, 10):
            raise ValueError(
                "recipient_id skal indeholde 10 cifre for CPR "
                "eller 8 cifre for CVR."
            )

        # Opretter KombitAccess ud fra q-serviceplatformens
        # eksisterende konfiguration.
        kombit_access = get_kombit_access()

        # Dette er et synkront opslag.
        #
        # send_digital_post() kalder wrapperen med
        # asyncio.to_thread(), så den asynkrone proces venter
        # på resultatet uden at blokere event-loopet.
        is_registered = (
            serviceplatform_digital_post.is_registered(
                id_=normalized_recipient_id,
                service="digitalpost",
                kombit_access=kombit_access,
            )
        )

        # Beskytter mod et ændret eller uventet output fra
        # q-serviceplatformen.
        if not isinstance(is_registered, bool):
            raise TypeError(
                "q-serviceplatformens is_registered() "
                "returnerede ikke True eller False."
            )

        return is_registered



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
        delivery_method: str,
        address: dict[str, str] | None,
        documents: list[dict[str, Any]],
        status_message: str,
    ) -> dict[str, Any]:
        """
        Bygger JSON-data til ATS-itemet.

        Input:
            forsendelses_id:
                Haderslevs unikke ID for forsendelsen.

            recipient_id:
                Normaliseret CPR- eller CVR-nummer uden
                bindestreg og mellemrum.

            recipient_id_type:
                Enten CPR eller CVR.

            subject:
                Forsendelsens emne.

            source_process:
                Navnet på processen, som bestilte forsendelsen.

            source_item_id:
                Den kaldende process egen reference.

            delivery_method:
                Den valgte leveringsmetode:

                - ONLY_DIGITAL_POST
                - DIGITAL_OR_PHYSICAL_POST

            address:
                Modtagerens navn og fysiske adresse.

                Værdien er None ved ONLY_DIGITAL_POST.

                Ved DIGITAL_OR_PHYSICAL_POST er værdien en
                dictionary med den validerede adresse.

            documents:
                Referencer til hoveddokument og eventuelle bilag,
                som allerede er uploadet til SharePoint.

            status_message:
                Den tekst, som vises som Message på ATS-itemet.

        Output:
            En dictionary med:

            - box
            - defer
            - state
            - status

            Dictionaryen kan sendes direkte til:

                workqueue.add_item(data=item_data, ...)

            box indeholder leveringsmetode og eventuelle
            adresseoplysninger, så worker-processen senere kan
            opbygge det korrekte kald til q-serviceplatformen.
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

                # Angiver om worker-processen kun må sende Digital Post,
                # eller om fysisk post også må anvendes.
                "delivery_method": delivery_method,

                # Adresse er None ved ONLY_DIGITAL_POST.
                # Ved DIGITAL_OR_PHYSICAL_POST indeholder feltet
                # den validerede modtageradresse.
                "address": address,

                # Referencer til dokumenter gemt i SharePoint.
                "documents": documents,

                # Felter til worker-processens behandling.
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
            "state": [
                f"Digital Post bestilt {created_at}"
            ],
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
        delivery_method: DeliveryMethod,
        attachments: list[DigitalPostAttachment],
        address: DigitalPostAddress | None,
    ) -> dict[str, Any]:
        """
        Validerer hele bestillingen før første SharePoint-upload.

        Input:
            pdf_content:
                Hoveddokumentets PDF-indhold som bytes.

            file_name:
                Det filnavn modtageren skal se.

            cpr_or_cvr:
                Modtagerens CPR- eller CVR-nummer.

            subject:
                Forsendelsens emne.

            source_process:
                Navnet på processen, som bestiller forsendelsen.

            source_item_id:
                Processens egen reference til arbejdet.

            delivery_method:
                Angiver, om forsendelsen kun må sendes som
                Digital Post, eller om fysisk post også må bruges.

            attachments:
                Liste med eventuelle PDF-bilag.

            address:
                Modtagerens aktuelle navn og adresse.

                Adresse er kun påkrævet ved:

                DeliveryMethod.DIGITAL_OR_PHYSICAL_POST

                Adresseoplysningerne kan med fordel hentes med:

                DatafordelerClient.get_aktuel_navn_og_adresse(...)

        Output:
            En normaliseret dictionary med:

            - recipient_id
            - recipient_id_type
            - subject
            - source_process
            - source_item_id
            - delivery_method
            - address
            - documents

            Funktionen uploader ikke filer og opretter ikke noget
            i Automation Server.
        """

        # ----------------------------------------------------
        # LEVERINGSMETODE
        # ----------------------------------------------------
        if not isinstance(
            delivery_method,
            DeliveryMethod,
        ):
            raise TypeError(
                "delivery_method skal være en "
                "DeliveryMethod-værdi."
            )

        # ----------------------------------------------------
        # HOVEDDOKUMENT
        # ----------------------------------------------------
        main_document = DigitalPost._validate_pdf(
            content=pdf_content,
            file_name=file_name,
            role="MAIN",
        )

        # ----------------------------------------------------
        # BILAG
        # ----------------------------------------------------
        if not isinstance(attachments, list):
            raise TypeError(
                "attachments skal være en liste."
            )

        documents = [main_document]

        file_names = {
            main_document["file_name"].casefold()
        }

        for attachment in attachments:
            if not isinstance(
                attachment,
                DigitalPostAttachment,
            ):
                raise TypeError(
                    "Alle bilag skal være "
                    "DigitalPostAttachment-objekter."
                )

            validated_attachment = (
                DigitalPost._validate_pdf(
                    content=attachment.content,
                    file_name=attachment.file_name,
                    role="ATTACHMENT",
                )
            )

            normalized_name = (
                validated_attachment[
                    "file_name"
                ].casefold()
            )

            if normalized_name in file_names:
                raise ValueError(
                    "Hoveddokument og bilag skal have "
                    "forskellige filnavne."
                )

            file_names.add(normalized_name)
            documents.append(validated_attachment)

        # ----------------------------------------------------
        # SAMLET DOKUMENTSTØRRELSE
        # ----------------------------------------------------
        total_size = sum(
            len(document["content"])
            for document in documents
        )

        if total_size > MAX_TOTAL_SIZE_BYTES:
            raise ValueError(
                "Forsendelsens samlede størrelse er "
                f"{total_size} bytes. Maksimum er "
                f"{MAX_TOTAL_SIZE_BYTES} bytes."
            )

        # ----------------------------------------------------
        # CPR ELLER CVR
        # ----------------------------------------------------
        if not isinstance(cpr_or_cvr, str):
            raise TypeError(
                "cpr_or_cvr skal være tekst."
            )

        recipient_id = re.sub(
            r"\D",
            "",
            cpr_or_cvr,
        )

        if len(recipient_id) == 10:
            recipient_id_type = "CPR"

        elif len(recipient_id) == 8:
            recipient_id_type = "CVR"

        else:
            raise ValueError(
                "cpr_or_cvr skal indeholde 10 cifre "
                "for CPR eller 8 cifre for CVR."
            )

        # ----------------------------------------------------
        # ADRESSE
        # ----------------------------------------------------
        validated_address = None

        if (
            delivery_method
            == DeliveryMethod.DIGITAL_OR_PHYSICAL_POST
        ):
            if recipient_id_type != "CPR":
                raise ValueError(
                    "DIGITAL_OR_PHYSICAL_POST understøtter "
                    "foreløbigt kun modtagere med CPR-nummer."
                )

            if not isinstance(
                address,
                DigitalPostAddress,
            ):
                raise TypeError(
                    "address skal være et "
                    "DigitalPostAddress-objekt ved "
                    "DIGITAL_OR_PHYSICAL_POST."
                )

            name = DigitalPost._require_text(
                address.name,
                "address.name",
            )

            street_name = DigitalPost._require_text(
                address.street_name,
                "address.street_name",
            )

            house_number = DigitalPost._require_text(
                address.house_number,
                "address.house_number",
            )

            postal_code = DigitalPost._require_text(
                address.postal_code,
                "address.postal_code",
            )

            city = DigitalPost._require_text(
                address.city,
                "address.city",
            )

            country_code = DigitalPost._require_text(
                address.country_code,
                "address.country_code",
            ).upper()

            if (
                country_code == "DK"
                and (
                    len(postal_code) != 4
                    or not postal_code.isdigit()
                )
            ):
                raise ValueError(
                    "address.postal_code skal indeholde "
                    "præcis 4 cifre for en dansk adresse."
                )

            validated_address = {
                "name": name,
                "street_name": street_name,
                "house_number": house_number,
                "postal_code": postal_code,
                "city": city,
                "floor": str(
                    address.floor or ""
                ).strip(),
                "door": str(
                    address.door or ""
                ).strip(),
                "co_name": str(
                    address.co_name or ""
                ).strip(),
                "country_code": country_code,
            }

        elif address is not None:
            # Ved ONLY_DIGITAL_POST er adressen ikke nødvendig.
            # Den udelades fra ATS-itemet for at undgå at gemme
            # personoplysninger, som processen ikke har brug for.
            validated_address = None

        # ----------------------------------------------------
        # NORMALISERET OUTPUT
        # ----------------------------------------------------
        return {
            "recipient_id": recipient_id,
            "recipient_id_type": recipient_id_type,
            "subject": DigitalPost._require_text(
                subject,
                "subject",
            ),
            "source_process": DigitalPost._require_text(
                source_process,
                "source_process",
            ),
            "source_item_id": DigitalPost._require_text(
                str(source_item_id),
                "source_item_id",
            ),
            "delivery_method": delivery_method.value,
            "address": validated_address,
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
