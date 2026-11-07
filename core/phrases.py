"""Fixed wording in English and Hinglish. Numbers, OC numbers and quotes are never translated."""

P = {
    "en": {
        "disclaimer": "Unofficial tool based on publicly available NPCI circulars. Verify with NPCI before acting.",
        "corpus_as_of": "Circulars indexed up to {date}.",
        "no_oc_sets_this": "No indexed OC sets this",
        "unconfirmed": "Unconfirmed",
        "earlier": "Earlier (superseded): {text}",
        "withdrawn": "Withdrawn (no longer in force): {text}",
        "row_withdrawn": "No longer in force; see the withdrawn line below",
        "bank_managed": "No indexed OC sets this. NPCI's circulars neither fix how many transactions a user can send nor say that banks should manage it. This answer does not say who sets it; check with your bank.",
        "closed_by": "Why it is no longer in force: {ref}",
        "oc_withdrawn": "OC {oc} has been withdrawn by NPCI (listed in Annexure G of the UPI Consolidated Circular, 18 Sep 2026), so it is no longer in force. What follows is what it said.",
        "history_verdict": "{label}: {old} was the limit earlier (now superseded); the current limit is {new}.",
        "effective": "effective {date}",
        "dev_unverified": "Development mode: these facts are not human-verified yet.",
        "refusal_scope": "I can only answer questions about NPCI UPI Operating Circulars in my index, so I cannot help with this one.",
        "refusal_bank": "Limits set by an individual bank or app are not in NPCI circulars, so I cannot tell you your own limit. I can tell you the limits NPCI circulars set for the UPI ecosystem: ask for P2P, P2M, P2PM or UPI Lite.",
        "refusal_advice": "I report what NPCI circulars say; I do not give advice or recommendations. Ask what a circular requires or allows, for example the limits for P2P, P2PM or P2M.",
        "clarify_limit": "Which limit do you mean?",
        "chips_limit": ["P2P limit", "P2M limit", "P2PM limit", "UPI Lite limit"],
        "not_public": "OC {oc} exists{title}, but NPCI has not made its PDF public (it is member-only), so I cannot summarise it or state what it says.",
        "not_public_title": " (listed by NPCI as: {title})",
        "oc_not_found": "I could not find OC {oc} in the indexed circulars. It may not be public, or it may not be indexed yet.",
        "code_not_mentioned": "No indexed OC mentions {family} {code}, so I cannot state a rule for it.",
        "code_mention_only": "{family} {code} is mentioned in {n} indexed OC(s), but none of them sets a limit for it.",
        "code_unknown_reverse": "I could not find a merchant category matching that description in the indexed OCs.",
        "no_facts": "I do not have verified limit facts for this question.",
        "passages": "I could not produce a verified answer. These are the most relevant passages from the circulars.",
        "not_found": "I could not find this in the indexed circulars, and I will not guess.",
        "thin": "Only {n} indexed circular(s) mention this topic, so the answer may be incomplete.",
        "llm_down": "The language model is not available right now, so here are the most relevant passages instead.",
        "p2m_hint": "Higher limits apply to specific merchant categories (MCC). Ask with an MCC or a category name, for example jewellery or insurance.",
    },
    "hinglish": {
        "disclaimer": "Ye ek unofficial tool hai jo public NPCI circulars par based hai. Kuch karne se pehle NPCI se verify karein.",
        "corpus_as_of": "Circulars {date} tak index hain.",
        "no_oc_sets_this": "Kisi indexed OC mein ye tay nahi hai",
        "unconfirmed": "Unconfirmed",
        "earlier": "Pehle (superseded): {text}",
        "withdrawn": "Withdrawn (ab lagu nahi): {text}",
        "row_withdrawn": "Ab lagu nahi hai; neeche withdrawn line dekhein",
        "bank_managed": "Kisi indexed OC mein ye tay nahi hai. NPCI ke circulars na to ye tay karte hain ki user kitni transactions bhej sakta hai, na ye kehte hain ki bank ise manage kare. Ye jawab bhi nahi batata ki ye kaun tay karta hai; apni bank se confirm karein.",
        "closed_by": "Ab lagu kyun nahi hai: {ref}",
        "oc_withdrawn": "OC {oc} ko NPCI ne withdraw kar diya hai (UPI Consolidated Circular, 18 Sep 2026 ke Annexure G mein), isliye ab lagu nahi hai. Neeche wahi hai jo usme likha tha.",
        "history_verdict": "{label}: {old} pehle ki limit thi (ab superseded); abhi ki limit {new} hai.",
        "effective": "{date} se",
        "dev_unverified": "Development mode: ye facts abhi human-verified nahi hain.",
        "refusal_scope": "Main sirf index mein maujood NPCI UPI Operating Circulars ke sawalon ka jawab de sakta hoon, isliye isme madad nahi kar sakta.",
        "refusal_bank": "Kisi bank ya app ki apni limit NPCI circulars mein nahi hoti, isliye main aapki apni limit nahi bata sakta. NPCI circulars UPI ecosystem ke liye jo limits tay karte hain wo bata sakta hoon: P2P, P2M, P2PM ya UPI Lite poochiye.",
        "refusal_advice": "Main sirf bata sakta hoon ki NPCI circulars kya kehte hain; salah ya recommendation nahi deta. Poochiye ki circular kya require ya allow karta hai, jaise P2P, P2PM ya P2M ki limits.",
        "clarify_limit": "Aap kaunsi limit ke baare mein poochh rahe hain?",
        "chips_limit": ["P2P limit", "P2M limit", "P2PM limit", "UPI Lite limit"],
        "not_public": "OC {oc} exist karta hai{title}, par NPCI ne uska PDF public nahi kiya (wo member-only hai), isliye main uska summary ya content nahi bata sakta.",
        "not_public_title": " (NPCI ki list mein: {title})",
        "oc_not_found": "OC {oc} mujhe indexed circulars mein nahi mila. Ho sakta hai wo public na ho, ya abhi index na hua ho.",
        "code_not_mentioned": "Koi bhi indexed OC {family} {code} ka zikr nahi karta, isliye main uske liye koi rule nahi bata sakta.",
        "code_mention_only": "{family} {code} ka zikr {n} indexed OC mein hai, par kisi mein bhi uski limit tay nahi hai.",
        "code_unknown_reverse": "Is description se match karti merchant category mujhe indexed OCs mein nahi mili.",
        "no_facts": "Is sawal ke liye mere paas verified limit facts nahi hain.",
        "passages": "Main verified jawab nahi bana paaya. Circulars ke sabse relevant passages ye hain.",
        "not_found": "Ye mujhe indexed circulars mein nahi mila, aur main andaaza nahi lagaunga.",
        "thin": "Sirf {n} indexed circular is topic ka zikr karte hain, isliye jawab adhoora ho sakta hai.",
        "llm_down": "Language model abhi available nahi hai, isliye sabse relevant passages dikha raha hoon.",
        "p2m_hint": "Kuch merchant categories (MCC) ke liye ooncha limit hota hai. MCC ya category ka naam (jaise jewellery, insurance) ke saath poochiye.",
    },
}


def t(lang: str, key: str, **kw) -> str:
    table = P.get(lang) or P["en"]
    s = table.get(key, P["en"][key])
    return s.format(**kw) if kw else s


def fmt_inr(v) -> str:
    """Indian digit grouping: 100000 -> ₹1,00,000."""
    n = int(round(float(v)))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + "₹" + s


def fmt_value(value, unit: str) -> str:
    if unit == "INR":
        return fmt_inr(value)
    n = int(float(value))
    return f"{n} transaction" + ("" if n == 1 else "s")


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date(iso: str) -> str:
    """2021-10-31 -> 31 Oct 2021 (anything else is returned unchanged)."""
    try:
        y, m, d = iso.split("-")
        return f"{int(d)} {_MONTHS[int(m) - 1]} {y}"
    except (ValueError, IndexError, AttributeError):
        return iso
