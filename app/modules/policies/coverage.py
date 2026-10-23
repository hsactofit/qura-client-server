"""The full policy picture shared by the portal and the CRM.

``policies.details`` (portal) and ``crm.policies.details -> 'coverage'`` (CRM)
hold the same JSON object, so whatever the AI reads from a policy document (or an
advisor corrects in the CRM) means the same thing on both sides:

    {
      "plan_name": str | None,
      "insured_name": str | None,
      "policyholder_mobile": str | None,
      "policyholder_email": str | None,
      "policyholder_address": str | None,
      "members": [{"name", "relationship", "age", "date_of_birth",
                   "sum_insured", "pre_existing_diseases"}],
      "vehicle": {"registration_number", "make", "model", "variant",
                  "manufacturing_year", "fuel_type", "idv", "engine_number",
                  "chassis_number", "cubic_capacity", "seating_capacity",
                  "previous_policy"} | None,
      "key_features": {"room_rent_limit", "co_payment", "deductible",
                       "no_claim_bonus", "pre_hospitalization",
                       "post_hospitalization", "restore_benefit",
                       "add_ons": [str]},
      "life": {"policy_term", "premium_payment_term", "maturity_date",
               "death_benefit_payout",
               "riders": [{"name", "sum_insured", "premium"}]} | None,
      "travel": {"destination", "trip_start", "trip_end", "trip_type",
                 "sum_insured_currency", "sum_insured_foreign"} | None,
      "property": {"risk_address", "property_type", "building_sum_insured",
                   "contents_sum_insured"} | None,
      "premium_breakdown": {"net_premium", "gst"} | None,
      "waiting_periods": [str],
      "claim_support": {"helpline", "email", "steps": [str]},
      "summary": str | None,
    }

``life`` / ``travel`` / ``property`` / ``premium_breakdown`` are only set for
the policy types they apply to (None otherwise).

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
    "PERSONAL_ACCIDENT": "accident",
    "COMMERCIAL": "business",
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


def _date(value: Any) -> str | None:
    text = _s(value, 10)
    if not text or len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    return text if text.replace("-", "").isdigit() else None


def _block(values: dict[str, Any]) -> dict[str, Any] | None:
    """A type-specific block, or None when nothing in it is known."""
    return values if any(v not in (None, []) for v in values.values()) else None


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
                "date_of_birth": _date(m.get("date_of_birth")),
                "sum_insured": _num(m.get("sum_insured")),
                "pre_existing_diseases": _s(m.get("pre_existing_diseases"), 300),
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
        "engine_number": _s(vehicle_raw.get("engine_number"), 60),
        "chassis_number": _s(vehicle_raw.get("chassis_number"), 60),
        "cubic_capacity": _s(vehicle_raw.get("cubic_capacity"), 20),
        "seating_capacity": _s(vehicle_raw.get("seating_capacity"), 20),
        "previous_policy": _s(vehicle_raw.get("previous_policy"), 200),
    }
    features = _dict(data.get("key_features"))
    claim = _dict(data.get("claim_support"))
    life = _dict(data.get("life"))
    travel = _dict(data.get("travel"))
    prop = _dict(data.get("property"))
    premium = _dict(data.get("premium_breakdown"))
    riders = []
    for r in life.get("riders") or []:
        r = _dict(r)
        rider_name = _s(r.get("name"), 200)
        if rider_name:
            riders.append(
                {
                    "name": rider_name,
                    "sum_insured": _num(r.get("sum_insured")),
                    "premium": _num(r.get("premium")),
                }
            )
    return {
        "plan_name": _s(data.get("plan_name"), 200),
        "insured_name": _s(data.get("insured_name"), 200),
        "policyholder_mobile": _s(data.get("policyholder_mobile"), 20),
        "policyholder_email": _s(data.get("policyholder_email"), 320),
        "policyholder_address": _s(data.get("policyholder_address"), 400),
        "members": members[:20],
        "vehicle": vehicle if any(v is not None for v in vehicle.values()) else None,
        "key_features": {
            "room_rent_limit": _s(features.get("room_rent_limit")),
            "co_payment": _s(features.get("co_payment")),
            "deductible": _s(features.get("deductible")),
            "no_claim_bonus": _s(features.get("no_claim_bonus")),
            "pre_hospitalization": _s(features.get("pre_hospitalization")),
            "post_hospitalization": _s(features.get("post_hospitalization")),
            "restore_benefit": _s(features.get("restore_benefit")),
            "add_ons": _str_list(features.get("add_ons")),
        },
        "life": _block(
            {
                "policy_term": _s(life.get("policy_term"), 60),
                "premium_payment_term": _s(life.get("premium_payment_term"), 100),
                "maturity_date": _date(life.get("maturity_date")),
                "death_benefit_payout": _s(life.get("death_benefit_payout"), 200),
                "riders": riders[:10],
            }
        ),
        "travel": _block(
            {
                "destination": _s(travel.get("destination"), 300),
                "trip_start": _date(travel.get("trip_start")),
                "trip_end": _date(travel.get("trip_end")),
                "trip_type": _s(travel.get("trip_type"), 60),
                "sum_insured_currency": _s(travel.get("sum_insured_currency"), 3),
                "sum_insured_foreign": _num(travel.get("sum_insured_foreign")),
            }
        ),
        "property": _block(
            {
                "risk_address": _s(prop.get("risk_address"), 400),
                "property_type": _s(prop.get("property_type"), 200),
                "building_sum_insured": _num(prop.get("building_sum_insured")),
                "contents_sum_insured": _num(prop.get("contents_sum_insured")),
            }
        ),
        "premium_breakdown": _block(
            {"net_premium": _num(premium.get("net_premium")), "gst": _num(premium.get("gst"))}
        ),
        "waiting_periods": _str_list(data.get("waiting_periods")),
        "claim_support": {
            "helpline": _s(claim.get("helpline"), 100),
            "email": _s(claim.get("email"), 320),
            "steps": _str_list(claim.get("steps"), 12),
        },
        "summary": _s(data.get("summary"), 1500),
    }


_OPTIONAL_BLOCKS = ("vehicle", "life", "travel", "property", "premium_breakdown")


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
            if key in _OPTIONAL_BLOCKS and not any(
                v not in (None, []) for v in merged[key].values()
            ):
                merged[key] = None
        elif value not in (None, [], ""):
            merged[key] = value
    return merged
