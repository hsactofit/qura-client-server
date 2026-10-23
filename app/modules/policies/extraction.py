"""AI-assisted policy document extraction.

This turns an uploaded policy document into a set of *suggested* fields for the
user to review. It is strictly a convenience: extraction is NEVER treated as
authoritative, and the result is only ever ``verification_status = self_reported``
until a user confirms it.

Key guarantees:
- When no provider is configured (``QURA_OPENAI_API_KEY`` empty), extraction is
  reported as UNAVAILABLE via :class:`ExtractionUnavailable`. We never fabricate
  values to simulate success.
- Any field the model cannot determine is ``None`` (explicit missing state),
  never a guess.
- Secrets, raw document bytes, and model stack traces are kept out of logs and
  out of error messages returned to the client.

The provider is an OpenAI-compatible Chat Completions / Responses API, selected
to match the reference backend's approach while using Qura-owned configuration.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.core.uploads import DetectedFile
from app.modules.policies import coverage

logger = logging.getLogger("qura.policies.extraction")

# The canonical fields we ask the model for. These map 1:1 onto the columns the
# upload endpoint persists, plus a few review-only hints the UI can show.
EXTRACTION_FIELDS = (
    "policy_number",
    "policy_type",
    "insurer_name",
    "coverage_amount",
    "premium_amount",
    "premium_frequency",
    "start_date",
    "end_date",
    "nominee_name",
    "nominee_relationship",
)

_MAX_TEXT_CHARS = 40000
_MAX_OUTPUT_TOKENS = 6000
_MAX_SCAN_PAGES = 8
_SCAN_DPI = 170

_SYSTEM_PROMPT = """
You read Indian insurance policy documents (health, motor, life/term, travel,
home, personal accident, business) for a policyholder and their insurance advisor.
Return ONLY a valid JSON
object, exactly as printed in the document. Use null (or an empty list) for
anything not clearly stated. Never guess or invent.

Return ONLY this JSON shape (no markdown, no commentary):
{
  "policy_number": string | null,
  "policy_type": "health" | "motor" | "life" | "travel" | "home" | "accident" | "business"
                 | "other" | null,
  "insurer_name": string | null,
  "coverage_amount": number | null,
  "premium_amount": number | null,
  "premium_frequency": "annual" | "semi-annual" | "quarterly" | "monthly" | "one-time" | null,
  "start_date": "YYYY-MM-DD" | null,
  "end_date": "YYYY-MM-DD" | null,
  "nominee_name": string | null,
  "nominee_relationship": string | null,
  "benefits": [string],
  "exclusions": [string],
  "details": {
    "plan_name": string | null,
    "insured_name": string | null,
    "policyholder_mobile": string | null,
    "policyholder_email": string | null,
    "policyholder_address": string | null,
    "members": [{"name": string, "relationship": string | null, "age": number | null,
                 "date_of_birth": "YYYY-MM-DD" | null, "sum_insured": number | null,
                 "pre_existing_diseases": string | null}],
    "vehicle": {"registration_number": string | null, "make": string | null, "model": string | null,
                "variant": string | null, "manufacturing_year": string | null,
                "fuel_type": string | null, "idv": number | null,
                "engine_number": string | null, "chassis_number": string | null,
                "cubic_capacity": string | null, "seating_capacity": string | null,
                "previous_policy": string | null} | null,
    "key_features": {"room_rent_limit": string | null, "co_payment": string | null,
                     "deductible": string | null, "no_claim_bonus": string | null,
                     "pre_hospitalization": string | null, "post_hospitalization": string | null,
                     "restore_benefit": string | null, "add_ons": [string]},
    "life": {"policy_term": string | null, "premium_payment_term": string | null,
             "maturity_date": "YYYY-MM-DD" | null, "death_benefit_payout": string | null,
             "riders": [{"name": string, "sum_insured": number | null,
                         "premium": number | null}]} | null,
    "travel": {"destination": string | null, "trip_start": "YYYY-MM-DD" | null,
               "trip_end": "YYYY-MM-DD" | null, "trip_type": string | null,
               "sum_insured_currency": string | null, "sum_insured_foreign": number | null} | null,
    "property": {"risk_address": string | null, "property_type": string | null,
                 "building_sum_insured": number | null,
                 "contents_sum_insured": number | null} | null,
    "premium_breakdown": {"net_premium": number | null, "gst": number | null} | null,
    "waiting_periods": [string],
    "claim_support": {"helpline": string | null, "email": string | null, "steps": [string]},
    "summary": string | null
  }
}

Rules:
- Monetary amounts as plain numbers: no currency symbols, commas, or spaces.
- Dates in YYYY-MM-DD. Indian documents print dates day-first: "01/12/2025" -> "2025-12-01".
- coverage_amount is the sum insured / sum assured in rupees; for motor it is the IDV.
  For a travel policy insured in a foreign currency, put that amount and its ISO
  currency code in travel.sum_insured_foreign / sum_insured_currency and leave
  coverage_amount null unless a rupee amount is printed.
- policy_type: "accident" for personal accident policies; "life" for term, endowment,
  ULIP and other life insurance; "business" for shop, office, fire, marine, liability
  and other commercial policies.
- Fill life / travel / property / vehicle only for policies of that kind (else null).
  life.riders: every rider with its own sum assured and premium. For life policies
  end_date is the maturity / expiry date and premium_frequency the premium mode.
- premium_breakdown: the premium before tax and the GST amount, when printed.
- members[].pre_existing_diseases: as declared in the schedule, if any.
- premium_amount is the total premium inclusive of taxes when available.
- insurer_name is the insurance company's name as commonly known (e.g. "ICICI Lombard").
- benefits / exclusions: short plain-English bullet phrases (max 20 each), most important first.
- members: every insured person listed (health/life/travel).
- waiting_periods: e.g. "30 days initial waiting period", "2 years for named ailments".
- claim_support.steps: the claim process in up to 5 short steps, only if the document describes it.
- summary: 2-3 plain-language sentences a policyholder understands: what is covered,
  for how much, until when, and the one or two most important limits.
- Output must be a single JSON object and nothing else.
""".strip()


class ExtractionError(RuntimeError):
    """Extraction was attempted but failed (bad document, provider error)."""


class ExtractionUnavailable(ExtractionError):
    """No extraction provider is configured, so extraction cannot run."""


def is_configured(settings: Settings) -> bool:
    return bool(settings.openai_api_key)


def _secret_fingerprint(api_key: str) -> str:
    if not api_key:
        return "none"
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:4]}...{api_key[-4:]}"


def empty_result() -> dict[str, Any]:
    """A fully-null extraction result (explicit missing fields, no fabrication)."""
    return dict.fromkeys(EXTRACTION_FIELDS)


def has_values(result: dict[str, Any]) -> bool:
    """True when an extraction found anything at all."""
    if any(result.get(field) is not None for field in EXTRACTION_FIELDS):
        return True
    if result.get("benefits") or result.get("exclusions"):
        return True
    details = result.get("details") or {}
    return bool(details.get("summary") or details.get("plan_name") or details.get("members"))


def _parse_json_response(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ExtractionError("Model did not return a JSON object")
    return parsed


def _normalise(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only known fields; coerce blanks to None. Never invents values.

    Besides the flat EXTRACTION_FIELDS the result carries ``benefits``,
    ``exclusions`` (string lists) and ``details`` (see coverage.py).
    """
    result = empty_result()
    for field in EXTRACTION_FIELDS:
        value = raw.get(field)
        if value in ("", [], {}):
            value = None
        result[field] = value
    result["benefits"] = coverage._str_list(raw.get("benefits"), 20)
    result["exclusions"] = coverage._str_list(raw.get("exclusions"), 20)
    result["details"] = coverage.normalize_details(raw.get("details"))
    return result


def _extract_pdf_text(data: bytes) -> str:
    """Local text extraction for digital PDFs (no AI, no network)."""
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 - malformed PDF
        logger.warning("Local PDF text extraction failed: %s", type(exc).__name__)
        return ""
    return "\n\n".join(p for p in pages if p.strip())[:_MAX_TEXT_CHARS]


def _render_pdf_pages(data: bytes) -> list[str]:
    """Render the first pages of a PDF to JPEG data URLs (for scanned documents)."""
    import io

    import pypdfium2 as pdfium

    urls: list[str] = []
    try:
        pdf = pdfium.PdfDocument(data)
        for index in range(min(len(pdf), _MAX_SCAN_PAGES)):
            image = pdf[index].render(scale=_SCAN_DPI / 72).to_pil().convert("RGB")
            buf = io.BytesIO()
            image.save(buf, "JPEG", quality=85)
            urls.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
    except Exception as exc:  # noqa: BLE001 - malformed PDF
        logger.warning("Scanned PDF rendering failed: %s", type(exc).__name__)
        return []
    return urls


async def _chat_completion(
    settings: Settings, messages: list[dict[str, Any]]
) -> dict[str, Any]:
    base = settings.openai_api_base.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    body = {
        "model": settings.openai_model_name,
        "messages": messages,
        "temperature": 0,
        "max_tokens": _MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=settings.openai_timeout_seconds) as client:
        resp = await client.post(
            f"{base}/chat/completions", headers=headers, json=body
        )
    if not resp.is_success:
        # Log status only; never the body (may echo document content/keys).
        logger.warning(
            "AI extraction HTTP %s (model=%s, key=%s)",
            resp.status_code,
            settings.openai_model_name,
            _secret_fingerprint(settings.openai_api_key),
        )
        raise ExtractionError("The extraction service returned an error")
    payload = resp.json()
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ExtractionError("The extraction service returned no content") from exc
    return _parse_json_response(content)


async def extract_policy(
    settings: Settings, *, data: bytes, detected: DetectedFile
) -> dict[str, Any]:
    """Extract suggested policy fields from a document.

    Raises :class:`ExtractionUnavailable` when no provider is configured and
    :class:`ExtractionError` on any extraction failure. Callers decide how to
    surface these; this function never returns fabricated data.
    """
    if not is_configured(settings):
        raise ExtractionUnavailable("Policy extraction is not configured")

    messages: list[dict[str, Any]]
    if detected.content_type == "application/pdf":
        text = _extract_pdf_text(data)
        # A scan often still has a few printed words; treat thin text as a scan.
        if len("".join(text.split())) >= 200:
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Policy document text:\n\n{text}"},
            ]
        else:
            # Scanned/textless PDF: send the rendered pages as images. Sending the
            # PDF file itself misread digits on scans in testing; page images at
            # "high" detail read them reliably.
            pages = _render_pdf_pages(data)
            if not pages:
                raise ExtractionError("Could not read the scanned document")
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Extract the policy details from these scanned pages.",
                        },
                        *(
                            {"type": "image_url", "image_url": {"url": url, "detail": "high"}}
                            for url in pages
                        ),
                    ],
                },
            ]
    else:
        b64 = base64.b64encode(data).decode()
        data_url = f"data:{detected.content_type};base64,{b64}"
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract the policy details."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ]

    try:
        raw = await _chat_completion(settings, messages)
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - network/JSON failure
        logger.warning("AI extraction failed: %s", type(exc).__name__)
        raise ExtractionError("Could not extract details from the document") from exc

    return _normalise(raw)
