"""Centralized deterministic vocabulary and policy constants.

The lists intentionally focus on high-signal support language in English, Bangla,
and common Banglish forms.  They are not a generative model and never execute
instructions embedded in a complaint.
"""
from __future__ import annotations

from app.schemas import CaseType, Department

BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "phishing": (
        "otp", "pin", "password", "passcode", "verification code", "security code",
        "scam", "fraud", "fake call", "suspicious call", "called me", "called from",
        "asked for my", "share my", "account blocked", "account will be blocked",
        "ওটিপি", "পিন", "পাসওয়ার্ড", "পাসওয়ার্ড", "প্রতার", "স্ক্যাম", "ভুয়া",
        "ভুয়া", "ফোন করেছে", "কল করেছে", "শেয়ার করতে", "শেয়ার করতে", "ব্লক",
    ),
    "wrong_transfer": (
        "wrong number", "wrong recipient", "wrong person", "sent by mistake",
        "transferred by mistake", "typed it wrong", "wrongly sent", "ভুল নম্বর",
        "ভুল নাম্বার", "ভুল ব্যক্ত", "ভুল করে পাঠ", "ভুল করে টাকা", "রং নাম্বার",
    ),
    "transfer_nonreceipt": (
        "didn't get it", "did not get it", "not received", "recipient did not receive",
        "receiver did not receive", "brother didn't get", "he didn't get", "পায়নি",
        "পাইনি", "পায়নি", "পাচ্ছে না", "পায় নি",
    ),
    "payment_failed": (
        "payment failed", "app showed failed", "transaction failed", "failed but",
        "balance deducted", "money deducted", "deducted from my balance", "charge failed",
        "পেমেন্ট ব্যর্থ", "পেমেন্ট ফেল", "ব্যর্থ দেখাচ্ছে", "টাকা কেটে", "ব্যালেন্স কেটে",
        "কেটে নিয়েছে", "কেটে নিয়েছে",
    ),
    "refund_request": (
        "refund", "refund my", "return my money", "changed my mind",
        "reverse it", "reversal", "রিফান্ড", "ফেরত", "ফিরিয়ে", "ফিরিয়ে", "টাকা ফেরত",
    ),
    "duplicate_payment": (
        "twice", "two times", "duplicate", "double charged", "charged twice",
        "deducted twice", "paid twice", "double deduction", "দুইবার", "দুবার", "দুই বার",
        "ডাবল", "দ্বিগুণ", "দুইবার কেটে",
    ),
    "merchant_settlement": (
        "settlement", "settled", "sales", "not settled", "settlement delay",
        "মার্চেন্ট", "সেটেলমেন্ট", "বিক্রির", "বিক্রয়", "নিষ্পত্তি",
    ),
    "agent_cash_in": (
        "cash in", "cash-in", "agent", "balance not reflected", "cash deposit",
        "এজেন্ট", "ক্যাশ ইন", "ক্যাশইন", "ব্যালেন্সে টাকা আসেনি", "ব্যালেন্সে আসে নি",
    ),
    "transfer": ("transfer", "sent", "send money", "send taka", "পাঠিয়েছি", "পাঠিয়েছি", "ট্রান্সফার"),
    "payment": ("paid", "pay", "payment", "bill", "recharge", "পেমেন্ট", "বিল", "রিচার্জ"),
}

# Keywords that look like prompt injection rather than a support fact.  They are
# stripped before reasoning, while ordinary adjacent complaint text is retained.
INJECTION_MARKERS: tuple[str, ...] = (
    "ignore previous", "ignore all", "system prompt", "developer message",
    "jailbreak", "override instructions", "reveal secret", "show hidden",
    "act as", "you are chatgpt", "prompt injection", "disregard",
    "আগের নির্দেশ", "নির্দেশ উপেক্ষা", "সিস্টেম প্রম্পট", "গোপন নির্দেশ",
)

DEPARTMENT_BY_CASE: dict[CaseType, Department] = {
    CaseType.wrong_transfer: Department.dispute_resolution,
    CaseType.payment_failed: Department.payments_ops,
    CaseType.refund_request: Department.customer_support,
    CaseType.duplicate_payment: Department.payments_ops,
    CaseType.merchant_settlement_delay: Department.merchant_operations,
    CaseType.agent_cash_in_issue: Department.agent_operations,
    CaseType.phishing_or_social_engineering: Department.fraud_risk,
    CaseType.other: Department.customer_support,
}

# Matching score tuning.  The values are deliberately explicit so a reviewer can
# audit why a transaction was selected.
MATCH_MINIMUM = 0.50
AMBIGUITY_MARGIN = 0.12
DUPLICATE_WINDOW_SECONDS = 10 * 60
