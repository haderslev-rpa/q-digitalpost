"""Fast konfiguration for q-digitalpost."""

# Ret værdien til det tekniske id på Digital Post-køen i ATS.
DIGITAL_POST_QUEUE_ID = 13

SHAREPOINT_SITE_NAME = "Automatisering"
SHAREPOINT_LIBRARY_NAME = "Digitalpost"

# Foreløbige grænser. Kan ændres senere, hvis SF1601 har andre grænser.
MAX_DOCUMENT_SIZE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_SIZE_BYTES = 50 * 1024 * 1024
