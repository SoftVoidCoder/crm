import csv
import io
import json
import os
import urllib.request


DEFAULT_SOURCE_ENV = {
    "banks": "KORDA_CLASSIFIER_BANKS_URL",
    "bank": "KORDA_CLASSIFIER_BANKS_URL",
    "bik": "KORDA_CLASSIFIER_BANKS_URL",
    "addresses": "KORDA_CLASSIFIER_ADDRESSES_URL",
    "address": "KORDA_CLASSIFIER_ADDRESSES_URL",
    "fias": "KORDA_CLASSIFIER_ADDRESSES_URL",
    "kladr": "KORDA_CLASSIFIER_ADDRESSES_URL",
    "okved": "KORDA_CLASSIFIER_OKVED_URL",
    "okved2": "KORDA_CLASSIFIER_OKVED_URL",
    "okpd": "KORDA_CLASSIFIER_OKPD2_URL",
    "okpd2": "KORDA_CLASSIFIER_OKPD2_URL",
    "units": "KORDA_CLASSIFIER_UNITS_URL",
    "unit": "KORDA_CLASSIFIER_UNITS_URL",
    "okei": "KORDA_CLASSIFIER_UNITS_URL",
}


def _clean(value) -> str:
    return str(value or "").strip()


def _source_url(classifier_type: str, source_url: str = "") -> str:
    if _clean(source_url):
        return _clean(source_url)
    env_name = DEFAULT_SOURCE_ENV.get(_clean(classifier_type).lower(), "")
    return _clean(os.getenv(env_name)) if env_name else ""


def _items_from_json(raw_text: str) -> list[dict]:
    payload = json.loads(raw_text)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data", "records", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = value.get("items") or value.get("data") or value.get("records")
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
    return []


def _items_from_csv(raw_text: str) -> list[dict]:
    sample = raw_text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except Exception:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(raw_text), dialect=dialect)
    return [dict(row) for row in reader if any(_clean(value) for value in row.values())]


def fetch_external_classifier_items(classifier_type: str, source_url: str = "", token: str = "", headers: dict | None = None, limit: int = 2000) -> dict:
    url = _source_url(classifier_type, source_url)
    if not url:
        return {"status": "error", "error": "source_url_required", "items": []}
    request_headers = {
        "Accept": "application/json, text/csv, text/plain;q=0.9",
        "User-Agent": "Korda-NSI-Classifier-Importer/1.0",
    }
    request_headers.update(headers or {})
    if _clean(token) and "Authorization" not in request_headers:
        request_headers["Authorization"] = f"Bearer {_clean(token)}"
    req = urllib.request.Request(url, headers=request_headers, method="GET")
    with urllib.request.urlopen(req, timeout=45) as response:
        content_type = (response.headers.get("Content-Type") or "").lower()
        raw_bytes = response.read()
    raw_text = raw_bytes.decode("utf-8-sig", errors="replace")
    if "json" in content_type or raw_text.lstrip().startswith(("{", "[")):
        items = _items_from_json(raw_text)
        source_format = "json"
    else:
        items = _items_from_csv(raw_text)
        source_format = "csv"
    max_items = max(1, min(int(limit or 2000), 10000))
    return {
        "status": "success",
        "source_url": url,
        "source_format": source_format,
        "count": len(items[:max_items]),
        "items": items[:max_items],
    }
