# config.py
# Centralized configurations for the NPCI UPI OC Assistant

import os

# ---------------------------------------------------------------------------
# LLM backend selection
# ---------------------------------------------------------------------------
# "groq"   -> Groq cloud API (fast, better quality, rate-limited / paid tiers)
# "ollama" -> local model via Ollama (private, unlimited, no API key; quality
#             and speed depend on the local model + hardware)
# Override at runtime with:  export LLM_PROVIDER=groq   (or ollama)
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()

# Ollama (local) settings — Ollama exposes an OpenAI-compatible API.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
OLLAMA_MODELS = {
    "qwen3:14b": "Qwen3 14B (local, balanced)",
    "qwen3:8b": "Qwen3 8B (local, faster)",
    "llama3:latest": "Llama 3 8B (local)",
}

# Domain acronyms/terms whose full meaning embeddings don't always capture
# well — map them directly to the OC number(s) that define them. Values are
# ordered MOST-CURRENT / most-authoritative first, so retrieval prioritises
# the latest circular in a family while still including its origin/addenda.
# Grounded in the indexed corpus (filename + in-text occurrence analysis),
# not general knowledge.
ACRONYM_TO_OC = {
    # --- dispute / complaint handling ---
    "udir": ["165", "98", "122"],       # 165 current refund API; 98 origin; 122 non-adherence
    "odr": ["145", "145A"],             # final ODR timeline + reminder addendum
    "tat": ["198"],                     # Revision of Disputes TAT
    "chargeback": ["184B", "184A", "184", "213"],
    # --- limits (specific families) ---
    "upi lite": ["169A", "169", "138", "205", "179"],  # 169A current, 169 set Rs500, 138 intro, 205 auto top-up
    "autopay": ["223", "151A", "151", "125", "125A"],  # 223 latest, 151A limit enh., 125A EMI non-revocation
    "afa": ["151", "151A"],             # AutoPay AFA limit
    "p2pm": ["192", "70"],              # 192 inward credit limits; 70 category intro
    "upi global": ["177A", "177", "117"],   # international acceptance limits + 117 origin
    "international": ["177A", "177", "117"],
    # --- entities / infrastructure ---
    "tpap": ["210", "159", "97"],       # 210 (FY24-25) supersedes 159 volume-cap guidelines
    "third party application": ["210", "159", "97"],  # spelled-out form of TPAP
    "third party app": ["210", "159", "97"],
    "volume cap": ["210", "159", "97"],
    "cbdc": ["170B", "170A", "170"],
    "ppi": ["134"],                     # RBI PPI interoperability adherence
    "upi circle": ["201", "201A", "201B"],
    "rrn": ["107A", "107"],
    "mcc": ["232", "34"],               # 232 gift-card MCC (FY26-27); 34 standardisation
    "ndc": ["66"],                      # Minimum NDC for sub-member banks
    "mapper": ["115", "115D", "115E"],  # Numeric UPI ID / UPI Number
    "upi number": ["115", "115D", "115E"],
    # --- mandates / transaction status ---
    "sbmd": ["128A"],                   # only occurrence in corpus (secondary-market mandate use case)
    "deemed debit": ["128A", "128"],
    "deemed approval": ["39A"],         # subject explicitly "Deemed Approval (DA)"
    "collect request": ["220", "76"],   # 220 = P2P collect discontinuation
    # --- onboarding / channels ---
    "aadhaar otp": ["116", "116A", "137"],
    "settlement cycle": ["222", "197"],
    # --- misc single-OC topics ---
    "nri": ["60"],                       # NR accounts in IMPS and UPI
    "nre": ["60"],
    "nro": ["60"],
}

# Default models and parameters
GROQ_MODEL = "openai/gpt-oss-20b"
AVAILABLE_MODELS = {
    "openai/gpt-oss-20b": "GPT-OSS 20B (fast, recommended default)",
    "openai/gpt-oss-120b": "GPT-OSS 120B (more capable, slower)",
}
