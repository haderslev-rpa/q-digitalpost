from q_cura_api.api_client import get  # funktion (GET-kald)

# ------------------------------------------------------------
# GET BORGER VIA CPR
# ------------------------------------------------------------
def get_borger_by_cpr(cpr: str):
    """
    Henter borger i CURA via CPR.
    """

    # --------------------------------------------------------
    # Fjern bindestreg (helt simpelt)
    # --------------------------------------------------------
    cpr = cpr.replace("-", "")  # streng (tekst)

    endpoint = (
        "Patient"
        f"?identifier={cpr}"
        "&_profile=http://curafhir.dk/p/CuraCitizen"
    )

    # --------------------------------------------------------
    # DEBUG
    # --------------------------------------------------------
    print("\n--- BUILD BORGER REQUEST ---")
    print("CPR efter replace:", cpr)
    print("Endpoint:", endpoint)

    data = get(endpoint)  # funktion (API-kald)

    # --------------------------------------------------------
    # Standard output
    # --------------------------------------------------------
    result = {
        "findes_borger_i_cura": False,  # flag (ja/nej)
        "CPR": cpr,                     # JSON (renset CPR)
        "borger_id": None,              # FHIR id
    }

    # --------------------------------------------------------
    # Udtræk borger_id hvis fundet
    # --------------------------------------------------------
    if isinstance(data, list) and len(data) > 0:
        resource = data[0].get("resource", {})  # dict (nøgle/værdi)
        borger_id = resource.get("id")           # streng (id)

        if borger_id:
            result["findes_borger_i_cura"] = True
            result["borger_id"] = borger_id

    return result