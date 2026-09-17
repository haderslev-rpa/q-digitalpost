
"""
Fast konfiguration for q-digitalpost.

VIGTIGT:
    DeliveryMethod.ONLY_DIGITAL_POST ER IKKE FÆRDIG ENDNU.

    Funktionen _is_registered_for_digital_post() i
    q_digitalpost/digital_post.py skal forbindes med
    q-serviceplatformens synkrone is_registered()-opslag,
    før ONLY_DIGITAL_POST må anvendes i produktion.

    DIGITAL_OR_PHYSICAL_POST kan testes separat, fordi denne
    leveringsmetode ikke bruger registreringsopslaget.
"""


# Ret værdien til det tekniske id på Digital Post-køen i ATS.
DIGITAL_POST_QUEUE_ID = 13

SHAREPOINT_SITE_NAME = "Automatisering"
SHAREPOINT_LIBRARY_NAME = "Digitalpost"

# Foreløbige grænser. Kan ændres senere, hvis SF1601 har andre grænser.
MAX_DOCUMENT_SIZE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_SIZE_BYTES = 50 * 1024 * 1024
