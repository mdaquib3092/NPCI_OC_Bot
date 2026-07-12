"""
Standalone test — POSTs a test row directly to the Google Form to debug
why submissions aren't appearing in the linked Sheet.

Run:
    python test_feedback_submit.py

Then check your Google Sheet for a new row. Also read the printed
status code / response below for clues.
"""

import requests

FEEDBACK_FORM_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSdwb6PqtjVbBNRnBZqmzhF6rA4MztuvrideAgnxBFv39WBfHA/formResponse"
)

payload = {
    "entry.2058716435": "debug-session-123",
    "entry.1688293492": "debug question",
    "entry.1835707990": "debug answer",
    "entry.2108472519": "👍 Helpful",
    "entry.1008379228": "debug comment",
}

resp = requests.post(FEEDBACK_FORM_URL, data=payload, timeout=10)

print("Status code:", resp.status_code)
print("Response length:", len(resp.text))
print("First 500 chars of response:\n", resp.text[:500])
print(
    "\nIf status is 200 but the Sheet still shows nothing, the most common "
    "cause is the form has 'Restrict to users in your organization / "
    "Require sign-in' enabled in Settings — this blocks anonymous POSTs "
    "like this one. Check: Form → Settings (gear icon) → General → make "
    "sure 'Restrict to [org] users' and 'Limit to 1 response' toggles are "
    "OFF, and 'Collect email addresses' is not set to a mode that forces "
    "sign-in."
)