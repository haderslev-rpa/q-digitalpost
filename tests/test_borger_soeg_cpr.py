from pprint import pprint  # funktion (pæn udskrift)
from q_cura_api.functionality.borger_soeg_cpr import get_borger_by_cpr  # funktion (borger-søgning)
from automation_server_client import AutomationServer, Credential
# -------------------------------------------------
# Init Automation Server
# -------------------------------------------------
AutomationServer.from_environment()
test_data_credential = Credential.get_credential("Q-CURA-API")
TEST_CPR = test_data_credential.data["cpr1"]  # 👈 dine testdata

print("\n🚀 LOKAL TEST: SØG BORGER")

result = get_borger_by_cpr(TEST_CPR)

pprint(result, width=120)