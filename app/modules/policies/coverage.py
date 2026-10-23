"""The full policy picture shared by the portal and the CRM.

``policies.details`` (portal) and ``crm.policies.details -> 'coverage'`` (CRM)
hold the same JSON object, so whatever the AI reads from a policy document (or an
advisor corrects in the CRM) means the same thing on both sides:

    {
      "plan_name": str | None,
      "insured_name": str | None,
      "policyholder_mobile": str | None,
      "policyholder_email": str | None,
      "members": [{"name", "relationship", "age", "sum_insured"}],
      "vehicle": {"registration_number", "make", "model", "variant",
                  "manufacturing_year", "fuel_type", "idv"} | None,
      "key_features": {"room_rent_limit", "co_payment", "deductible",
                       "no_claim_bonus", "add_ons": [str]},
      "waiting_periods": [str],
      "claim_support": {"helpline", "email", "steps": [str]},
      "summary": str | None,
    }

Benefits and exclusions live in their own policy columns. Everything here is a
best-effort reading: unknown values are ``None`` / empty, never guessed.

Also holds the vocabulary mapping between the two systems (CRM insurer codes and
categories vs. portal display names and policy types).
"""

from __future__ import annotations

from typing import Any

# CRM insurer codes (crm.policies.insurer_id) -> display names. Kept in step
# with Qura-crm-server src/services/pdfExtractor.ts INSURER_CODES.
INSURER_NAMES: dict[str, str] = {
    "TATA_AIG": "Tata AIG",
    "HDFC_ERGO": "HDFC ERGO",
    "ICICI_LOMBARD": "ICICI Lombard",
    "BAJAJ_ALLIANZ": "Bajaj Allianz",
    "GO_DIGIT": "Go Digit",
    "ZUNO": "Zuno",
    "SBI_GENERAL": "SBI General",
    "ROYAL_SUNDARAM": "Royal Sundaram",
    "LIBERTY": "Liberty General",
    "RELIANCE_GENERAL": "Reliance General",
    "NEW_INDIA": "New India Assurance",
    "UNITED_INDIA": "United India",
    "ORIENTAL": "Oriental Insurance",
    "NATIONAL": "National Insurance",
    "CHOLA_MS": "Chola MS",
    "IFFCO_TOKIO": "IFFCO Tokio",
    "KOTAK_GENERAL": "Kotak General",
    "FUTURE_GENERALI": "Future Generali",
    "MAGMA": "Magma HDI",
    "SHRIRAM": "Shriram General",
    "UNIVERSAL_SOMPO": "Universal Sompo",
    "ACKO": "Acko",
    "STAR_HEALTH": "Star Health",
    "NIVA_BUPA": "Niva Bupa",
    "CARE_HEALTH": "Care Health",
    "LIC": "LIC",
    "HDFC_LIFE": "HDFC Life",
    "OTHER": "Other insurer",
}

# CRM category -> portal policy_type, and back.
CATEGORY_TO_TYPE: dict[str, str] = {
    "MOTOR": "motor",
    "HEALTH": "health",
    "LIFE": "life",
    "PROPERTY": "home",
    "TRAVEL": "travel",
}


def insurer_display_name(code: str | None) -> str | None:
    if not code:
        return None
    return INSURER_NAMES.get(code, code.replace("_", " ").title())


def _s(value: Any, limit: int = 300) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:limit] if text else None


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("₹", "").strip()
        try:
            number = float(cleaned)
        except ValueError:
            return None
        return number if number >= 0 else None
    return None


def _str_list(value: Any, limit: int = 30) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [item for item in (_s(v, 400) for v in value) if item]
    return out[:limit]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_details(raw: Any) -> dict[str, Any]:
    """Coerce any (AI or CRM) details object to the canonical shape."""
    data = _dict(raw)
    members = []
    for m in data.get("members") or []:
        m = _dict(m)
        name = _s(m.get("name"), 200)
        if not name:
            continue
        age = _num(m.get("age"))
        members.append(
            {
                "name": name,
                "relationship": _s(m.get("relationship"), 60),
                "age": int(age) if age is not None else None,
                "sum_insured": _num(m.get("sum_insured")),
            }
        )
    vehicle_raw = _dict(data.get("vehicle"))
    vehicle = {
        "registration_number": (
            (_s(vehicle_raw.get("registration_number"), 40) or "")
            .upper()
            .replace(" ", "")
            .replace("-", "")
            or None
        ),
        "make": _s(vehicle_raw.get("make"), 120),
        "model": _s(vehicle_raw.get("model"), 200),
        "variant": _s(vehicle_raw.get("variant"), 200),
        "manufacturing_year": _s(vehicle_raw.get("manufacturing_year"), 10),
        "fuel_type": _s(vehicle_raw.get("fuel_type"), 40),
        "idv": _num(vehicle_raw.get("idv")),
    }
    features = _dict(data.get("key_features"))
    claim = _dict(data.get("claim_support"))
    return {
        "plan_name": _s(data.get("plan_name"), 200),
        "insured_name": _s(data.get("insured_name"), 200),
        "policyholder_mobile": _s(data.get("policyholder_mobile"), 20),
        "policyholder_email": _s(data.get("policyholder_email"), 320),
        "members": members[:20],
        "vehicle": vehicle if any(v is not None for v in vehicle.values()) else None,
        "key_features": {
            "room_rent_limit": _s(features.get("room_rent_limit")),
            "co_payment": _s(features.get("co_payment")),
            "deductible": _s(features.get("deductible")),
            "no_claim_bonus": _s(features.get("no_claim_bonus")),
            "add_ons": _str_list(features.get("add_ons")),
        },
        "waiting_periods": _str_list(data.get("waiting_periods")),
        "claim_support": {
            "helpline": _s(claim.get("helpline"), 100),
            "email": _s(claim.get("email"), 320),
            "steps": _str_list(claim.get("steps"), 12),
        },
        "summary": _s(data.get("summary"), 1500),
    }


def merge_details(base: Any, update: Any) -> dict[str, Any]:
    """Overlay ``update`` on ``base``: known values in ``update`` win."""
    merged = normalize_details(base)
    incoming = normalize_details(update)
    for key, value in incoming.items():
        if isinstance(value, dict):
            current = merged.get(key) or {}
            merged[key] = {
                k: (v if v not in (None, [], "") else current.get(k))
                for k, v in value.items()
            }
            if key == "vehicle" and not any(merged[key].values()):
                merged[key] = None
        elif value not in (None, [], ""):
            merged[key] = value
    return merged
