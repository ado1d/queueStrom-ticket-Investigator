"""Bilingual regex patterns and keyword dictionaries for the evidence engine.

Centralising these here keeps the deterministic core auditable and lets the
classifier, evidence engine, and safety module all share a single source of
truth for forbidden / helpful tokens.
"""
from __future__ import annotations

import re
from typing import Dict, List, Pattern

# ---------------------------------------------------------------------------
# Entity extraction patterns
# ---------------------------------------------------------------------------

# Amount: "5000 taka", "৫০০০ টাকা", "BDT 5000", "tk 200", "taka 1500",
# or bare numbers 100-999999 that look like monetary amounts in context.
AMOUNT_PATTERNS: List[Pattern[str]] = [
    re.compile(r"\b(\d{1,9}(?:[,]\d{2,3})?(?:\.\d+)?)\s*(taka|টাকা|tk|bdt)\b", re.IGNORECASE),
    re.compile(r"\b(bdt|টাকা|taka|tk)\s*(\d{1,9}(?:[,]\d{2,3})?(?:\.\d+)?)\b", re.IGNORECASE),
    # Bare number after "sent"/"transfer"/"pay"/"paid"/"cash in"/"cash out"
    # e.g. "I sent 2000 to" — captures 2000 as the amount.
    re.compile(r"\b(?:sent|send|transferred|transfer|paid|pay|cash[\s-]?in|cash[\s-]?out|deposit|deducted|charged|refund)\s+(\d{3,6}(?:,\d{2,3})?(?:\.\d+)?)\b", re.IGNORECASE),
]

# Bangla digits normalisation.
_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def normalise_text(text: str) -> str:
    """Lowercase + translate Bangla digits to ASCII + collapse whitespace."""
    lowered = (text or "").lower().translate(_BANGLA_DIGITS)
    # Collapse runs of whitespace to a single space so "wrong   number" still
    # matches the keyword "wrong number".
    return re.sub(r"\s+", " ", lowered).strip()


# Phone number pattern (Bangladesh mobile).
PHONE_PATTERN = re.compile(r"\b01\d{9}\b")
# Merchant ID: M followed by digits.
MERCHANT_ID_PATTERN = re.compile(r"\bM\d{2,}\b", re.IGNORECASE)
# Agent ID: A followed by digits.
AGENT_ID_PATTERN = re.compile(r"\bA\d{2,}\b", re.IGNORECASE)
# Generic alphanumeric counterparty hint.
# Excludes common English stop-words so "to the wrong person" doesn't capture
# "the" as a counterparty hint. Requires the captured group to start with a
# digit, +, or an uppercase letter (merchant/agent IDs) OR be a 4+ char word.
COUNTERPARTY_HINT_PATTERN = re.compile(
    r"\b(?:to|at|for|কাছে|কে)\s+([+0-9][0-9+\-\s]{3,}|[A-Z][A-Z0-9\-]{2,}|[a-z][a-z]{3,})\b",
    re.IGNORECASE,
)

# Time hints: rough, the matching layer only uses these to score proximity.
TIME_HINT_PATTERNS: Dict[str, Pattern[str]] = {
    "today": re.compile(r"\b(today|আজ|এই দিন|আজকে)\b", re.IGNORECASE),
    "yesterday": re.compile(r"\b(yesterday|গতকাল|কাল)\b", re.IGNORECASE),
    "morning": re.compile(r"\b(morning|সকাল)\b", re.IGNORECASE),
    "afternoon": re.compile(r"\b(afternoon|বিকাল|দুপুর)\b", re.IGNORECASE),
    "evening": re.compile(r"\b(evening|সন্ধ্যা|রাত)\b", re.IGNORECASE),
    "time_of_day": re.compile(r"\b(?:around|প্রায়)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|টা)?\b", re.IGNORECASE),
}

# ---------------------------------------------------------------------------
# Keyword dictionaries (English + Bangla + Banglish)
# ---------------------------------------------------------------------------

TRANSACTION_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "transfer": [
        "send", "sent", "transfer", "transferred", "send money", "sent money",
        "পাঠিয়েছি", "পাঠালাম", "ট্রান্সফার", "পাঠানো",
        "pathachi", "pathalam", "pathano", "transfer korechi",
    ],
    "payment": [
        "pay", "paid", "payment", "purchase", "bought",
        "পেমেন্ট", "পেমেন্ট করেছি", "কিনেছি",
        "payment korechi", "payment korlam",
    ],
    "cash_in": [
        "cash in", "cash-in", "deposit", "add money", "top up", "topup",
        "ক্যাশ ইন", "টাকা ঢুকেছে", "টাকা ঢোকানো",
        "taka dhukechhe", "taka dhukano",
    ],
    "cash_out": [
        "cash out", "cash-out", "withdraw", "withdrawal",
        "ক্যাশ আউট", "তুলেছি", "উত্তোলন",
        "tulechi", "uttolon",
    ],
    "settlement": [
        "settlement", "settle", "merchant payout", "payout",
        "সেটেলমেন্ট", "মার্চেন্ট পেমেন্ট",
    ],
    "refund": [
        "refund", "refunded", "return money", "money back",
        "ফেরত", "টাকা ফেরত", "রিফান্ড",
        "ferot", "taka ferot",
    ],
}

STATUS_CLAIM_KEYWORDS: Dict[str, List[str]] = {
    "deducted": [
        "deducted", "money deducted", "balance minus", "cut", "taken",
        "কাটা হয়েছে", "কেটে নিয়েছে", "ব্যালেন্স কমেছে",
        "kata hoyeche", "kate niyeche", "balance komeche",
    ],
    "failed": [
        "failed", "didn't go through", "not successful", "unsuccessful",
        "ব্যর্থ", "হয়নি", "সফল হয়নি",
        "byartho", "hoyni", "sofol hoyni",
    ],
    "not_received": [
        "not received", "didn't receive", "haven't got", "did not get", "missing",
        "didn't get", "hasn't arrived", "not yet received",
        "পাইনি", "হাতে পাইনি", "টাকা আসেনি", "আসেনি", "পায়নি",
        "paini", "hate paini", "taka aseni", "aseni",
    ],
    "pending": [
        "pending", "still waiting", "not yet",
        "পেন্ডিং", "অপেক্ষা",
        "pending ache", "opekkha",
    ],
    "completed": [
        "completed", "success", "successful", "done",
        "সফল", "হয়েছে",
        "sofol", "hoyse",
    ],
}

# Complaint topic keywords (used by classifier).
TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "wrong_number": [
        # English — single-word + multi-word variants
        "wrong number", "wrong recipient", "wrong person", "wrong account",
        "wrong people", "wrong user", "wrong mobile", "wrong phone",
        "sent to wrong", "sent to the wrong", "send to wrong", "to the wrong",
        "transferred to wrong", "transfer to wrong", "to wrong",
        "mistaken number", "mistaken recipient", "mistakenly sent",
        "mistakenly transferred", "mistakenly", "by mistake", "unintentionally",
        "accidentally sent", "accidentally transferred", "accidentally paid",
        "incorrect number", "incorrect recipient", "incorrect account",
        "not the intended", "not intended recipient",
        # Bangla + Banglish
        "ভুল নম্বর", "ভুল নাম্বার", "ভুল মানুষ", "ভুলে পাঠিয়েছি",
        "vul number", "vul manush", "vul namebar", "vul e pathiyechhi",
        "bhul number", "bhul e",
    ],
    "refund": [
        "refund", "money back", "return my money", "want my money back",
        "ফেরত দিন", "টাকা ফেরত", "টাকা ফেরত চাই",
        "taka ferot chai", "ferot din",
    ],
    "duplicate": [
        "twice", "two times", "double charged", "charged twice", "duplicate",
        "দুইবার", "দ্বিগুণ", "ডুপ্লিকেট",
        "duibar", "duighun",
    ],
    "settlement": [
        "settlement", "merchant settlement", "payout", "merchant payment",
        "সেটেলমেন্ট", "মার্চেন্ট পেমেন্ট আটকে",
    ],
    "agent_cash_in": [
        "agent cash in", "agent number", "agent did not", "agent didn't add",
        "এজেন্ট", "এজেন্ট নম্বরে",
        "agent number e", "agent taka dhukay nai",
    ],
    "phishing": [
        "otp", "pin", "password", "secret code", "verification code",
        "share my otp", "share my pin", "give my pin", "asked for otp",
        "otp দিয়েছি", "পিন দিয়েছি",
        "pin diyechhi", "otp diyechhi",
        "suspicious call", "fake call", "scam call", "fraud call",
        "সন্দেহজনক কল", "প্রতারণা", "ফেক কল",
    ],
}

# ---------------------------------------------------------------------------
# Safety blocklist
# ---------------------------------------------------------------------------

# Phrases that must NEVER appear in any output text field. Each pattern is
# matched case-insensitively. The sanitizer in app/safety.py handles the
# rewrites/redactions.
FORBIDDEN_OUTPUT_PHRASES: List[Pattern[str]] = [
    re.compile(r"\bpin\b", re.IGNORECASE),
    re.compile(r"\botp\b", re.IGNORECASE),
    re.compile(r"\bpassword\b", re.IGNORECASE),
    re.compile(r"\bsecret code\b", re.IGNORECASE),
    re.compile(r"\bverification code\b", re.IGNORECASE),
    re.compile(r"\b(?:full\s+)?card\s+number\b", re.IGNORECASE),
    re.compile(r"\b\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\b"),  # 16-digit card
    re.compile(r"\b(?:cvc|cvv)\b", re.IGNORECASE),
    re.compile(r"\bwe will refund\b", re.IGNORECASE),
    re.compile(r"\bwe have refunded\b", re.IGNORECASE),
    re.compile(r"\bwe'?ll refund\b", re.IGNORECASE),
    re.compile(r"\baccount (?:will be )?unblocked\b", re.IGNORECASE),
    re.compile(r"\byour money will be reversed\b", re.IGNORECASE),
]

# Prompt-injection patterns to strip from complaint text BEFORE it is used in
# templates (templates should never interpolate user text anyway, but the
# sanitizer also scrubs LLM-returned strings).
PROMPT_INJECTION_PATTERNS: List[Pattern[str]] = [
    re.compile(r"ignore (?:all )?previous (?:instructions|prompts)", re.IGNORECASE),
    re.compile(r"disregard (?:the )?system", re.IGNORECASE),
    re.compile(r"you are now (?:a|an) ", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\s*\|.*?\|\s*>", re.IGNORECASE),  # "<|...|>" style tokens
    re.compile(r"###\s*instruction", re.IGNORECASE),
]
