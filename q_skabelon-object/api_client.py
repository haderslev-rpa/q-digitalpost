import time  # modul (tid)
import requests  # modul (HTTP-kald)

from automation_server_client import AutomationServer, Credential  # klasse (AS-klient)

# -------------------------------------------------
# Init Automation Server
# -------------------------------------------------
AutomationServer.from_environment()  # funktion (forbind til AS)
credential = Credential.get_credential("API_CURA")  # objekt (credentials)

cfg = credential.data  # dict (konfiguration)

# -------------------------------------------------
# Konfiguration (matcher Blue Prism)
# -------------------------------------------------
BASE_URL = cfg["base_url"]  
# fx: https://haderslev.cura.columna.dk:20105/fhir-server/fhir/

ACCESS_TOKEN_URL = cfg["access_token_url"]
# /keycloak/generate-authentication-url?username=

AUTH_USERINFO_URL = cfg["auth_userinfo"]
# /auth/userinfo

SESSION_TOKEN_URL = cfg["session_token_url"]
# /auth/authorize

ORG_ID = cfg["org_id"]
USER_ROLE = cfg["user_role"]
API_VERSION = cfg["api_version"]

CURA_API_KEY = cfg["cura_api_key"]

USERNAME = credential.username
PASSWORD = credential.password

# -------------------------------------------------
# Token cache (hukommelse)
# -------------------------------------------------
_access_token = None
_access_token_expiry = 0

_session_token = None
_session_token_expiry = 0

TOKEN_BUFFER = 600  # sekunder

# -------------------------------------------------
# 1️⃣ Access token (Keycloak)
# -------------------------------------------------
def _get_access_token():
    """Henter og cacher access token."""  # funktion (genbrugelig kodeblok)
    global _access_token, _access_token_expiry

    if _access_token and time.time() < (_access_token_expiry - TOKEN_BUFFER):
        return _access_token

    # Step 1: hent authentication URL (TEXT!)
    r1 = requests.get(
        f"{ACCESS_TOKEN_URL}{USERNAME}",
        headers={"Accept": "text/plain"},
        timeout=30,
    )
    r1.raise_for_status()

    authentication_url = r1.text.strip().strip('"')

    # Step 2: login mod Keycloak
    r2 = requests.post(
        authentication_url,
        data={
            "grant_type": "password",
            "client_id": "fhir-server",
            "username": USERNAME,
            "password": PASSWORD,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/plain, */*",
        },
        timeout=30,
    )
    r2.raise_for_status()

    data = r2.json()
    _access_token = data["access_token"]
    _access_token_expiry = time.time() + int(data.get("expires_in", 3600))

    return _access_token

# -------------------------------------------------
# 2️⃣ VIGTIGT: userinfo (CURA-krav)
# -------------------------------------------------
def _validate_userinfo():
    """Validerer access token mod CURA."""  # funktion (obligatorisk trin)

    access_token = _get_access_token()

    r = requests.get(
        AUTH_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "CURA-API-KEY": CURA_API_KEY,
            "Accept": "application/json",
        },
        timeout=30,
    )

    r.raise_for_status()

# -------------------------------------------------
# 3️⃣ Session token (CURA authorize)
# -------------------------------------------------
def _get_session_token():
    """Henter og cacher session token."""  # funktion (genbrugelig kodeblok)
    global _session_token, _session_token_expiry

    if _session_token and time.time() < (_session_token_expiry - TOKEN_BUFFER):
        return _session_token

    access_token = _get_access_token()  # funktion (Keycloak token)

    r = requests.post(
        SESSION_TOKEN_URL,
        data={
            "organization": ORG_ID,
            "userRole": USER_ROLE,        # ✅ Systemadministrator
            "apiVersion": API_VERSION,
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "CURA-API-KEY": CURA_API_KEY,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=30,
    )

    if r.status_code >= 300:
        raise RuntimeError(
            f"Session-token fejl {r.status_code}: {r.text}"
        )

    data = r.json()["sessionToken"]
    _session_token = data["tokenString"]
    _session_token_expiry = time.time() + 3600

    return _session_token


# -------------------------------------------------
# Headers (fælles)
# -------------------------------------------------
def _auth_headers():
    """Bygger headers til FHIR-kald."""  # funktion (hjælpefunktion)
    return {
        "Authorization": f"Bearer {_get_access_token()}",
        "CURA-API-KEY": CURA_API_KEY,
        "CuraSessionToken": f"Bearer {_get_session_token()}",
    }


# -------------------------------------------------
# Public GET (som Prisme)
# -------------------------------------------------
def get(endpoint: str, raw: bool = False):
    """GET request til CURA FHIR API."""  # funktion (offentligt API)

    url = f"{BASE_URL}{endpoint}"
    r = requests.get(url, headers=_auth_headers(), timeout=30)
    r.raise_for_status()

    data = r.json()

    if raw:
        return data

    # FHIR: pak entry ud
    if isinstance(data, dict) and isinstance(data.get("entry"), list):
        return data["entry"]

    return data