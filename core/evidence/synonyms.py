"""Domain wording that questions and circulars express differently.

Users say "AutoPay interoperability"; the circulars say "view and port a mandate", "Merchant Identifier Code".
Each rule appends the circulars' own words to the search query (it never changes the question the
model sees). Extend this list as gaps are found.
"""

import re

RULES = [
    (r"auto[\s-]?pay.{0,20}interoperab|mandate.{0,20}interoperab|interoperab.{0,20}(auto[\s-]?pay|mandate)|"
     r"\bport(ing)?\b.{0,20}mandate|mandate.{0,20}\bport",
     "UPI Autopay mandate view mandate port mandate manage bank accounts Merchant Identifier Code MIC payee PSP lifecycle management"),
    (r"\bmdr\b|merchant discount rate", "MDR merchant discount rate charges zero MDR merchants"),
    (r"\btpap\b.{0,30}(cap|share)|market share", "TPAP volume cap market share 30% multi-bank model PSP"),
    (r"third[\s-]party app\w*|\btpaps?\b.{0,30}guideline|guideline.{0,30}\btpaps?\b", "TPAP third party application provider guidelines onboarding market share volume cap multi-bank"),
    (r"\bnri\b|\bnre\b|\bnro\b|non[\s-]resident", "NRE NRO non-resident external ordinary accounts crediting debiting NR accounts UPI IMPS"),
    (r"\bcbdc\b|digital rupee|e-?rupee", "RBI Digital Rupee CBDC UPI interoperability QR wallet"),
    (r"mcc.{0,20}standardi[sz]ation|standardi[sz]ation.{0,20}mcc", "MCC standardisation merchant category code compliance merchant onboarding"),
    (r"upi lite.{0,40}(launch|introduc|start|began|first)|(launch|introduc).{0,40}upi lite", "UPI Lite On-Device wallet introduction small value transactions 200 pilot"),
]


def expand(query: str) -> str:
    extra = [words for rx, words in RULES if re.search(rx, query, re.I)]
    return query + (" " + " ".join(extra) if extra else "")
