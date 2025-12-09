#!/usr/bin/env python3

import os
import json
import sys
import urllib.request
import urllib.error
import urllib.parse

LOG_DIR = os.path.join("/tmp", "paperless_test_logs")
PRED_DIR = "/pred_cache"


API_ROOT = os.environ["PAPERLESS_API_URL"]
API_KEY = os.environ["PAPERLESS_API_KEY"]
HELPER_URL = os.environ["HELPER_URL"]


def log(msg: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, "post_consume.log"), "a") as f:
        f.write(msg + "\n")


def call_llm_extract(ocr_text: str, doc_id: int | str) -> dict:
    payload = {
            "ocr": ocr_text,
            "doc_id": int(doc_id),
            }

    body = json.dumps(payload).encode('utf-8')

    url = f"{HELPER_URL}/extract"
    req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
            )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode('utf-8')
        if not text:
            return {}
        return json.loads(text)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        print(f"[post-consume] LLM extract failed for doc {doc_id}: {e}", flush=True)
        return {}


def api_req(method: str, endpoint: str, data: dict | None = None):
    """make request to Paperless API. Start path with `/`"""
    url = API_ROOT + endpoint
    headers = {
            "Authorization": f"Token {API_KEY}",
            "Accept": "application/json; version=6",
            }

    body = None

    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"


    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try: 
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")
            if text:
                return json.loads(text)
            return None
    except urllib.error.HTTPError as e:
        log(f"HTTP error {e.code} for {method} {url}: {e.read().decode('utf-8', 'ignore')}")
        raise
    except Exception as e:
        log(f"API request failed for {method} {url}: {e}")
        raise


def get_field_map():
    """Request id nums for custom fields {name: id}"""
    endpoint = "/api/custom_fields/"
    # print(f"url: {url}", file=sys.stdout, flush=True)
    for attempt in range(10):
        try:
            res = api_req("GET", endpoint)
            fields = res.get('results')
            print(f"got field map response: \n{fields}")
            id_dict = {f["name"]: f["id"] for f in fields}
            return id_dict
        except urllib.error.HTTPError as e:
            print(f"get_field_map attempt {attempt + 1} failed: {e}", file=sys.stdout, flush=True)
            time.sleep(2)
    raise RuntimeError("Could not reach the Paperless API after 10 retries", file=sys.stdout, flush=True)

FIELD_ID_DICT = get_field_map()
AMOUNT_ID = FIELD_ID_DICT.get("Amount")
DATE_ID = FIELD_ID_DICT.get("Purchase Date")

if AMOUNT_ID is None or DATE_ID is None:
    raise RuntimeError(
            f"Couldn't get fields by name."
            f"Amount -> {AMOUNT_ID}, "
            f"Purchase Date -> {DATE_ID}"
            )

def update_fields(fields: list[dict], amount: str, date: str) -> dict:
    new_cf = []
    for idx, field in enumerate(fields):
        cf = dict(field)
        if cf['field'] == AMOUNT_ID:
            cf['value'] = amount
        elif cf['field'] == DATE_ID:
            cf['value'] = date
        new_cf.append(cf)
    return {"custom_fields": new_cf}

def main() -> int:
    doc_id = os.environ.get("DOCUMENT_ID")
    if not doc_id:
        log("No doc id, nothing to do")
        return 0
#    log("=== New Doc added ===")
#    log(f"ID: {doc_id}")
#    log("")

    doc = api_req("GET", f"/api/documents/{doc_id}/?fields=id,content,custom_fields")
    content = (doc or {}).get("content") or ""
#    log(f"OCR length: {len(content)}")
#    log(f"OCR preview: {content[:200].replace(chr(10), ' ')}")

    pred = call_llm_extract(content, doc_id)
    print("[call_llm_extract] response: ", pred)
    amount = pred.get("amount")
    date = pred.get("purchase_date")

    print("amount", amount)
    print("date", date)

    amt_val = amount if amount else "0.00"
    date_val = date if date else "1970-01-01"

    print("amt_val", amt_val)
    print("date_val", date_val)

    custom_fields_data = update_fields(
            (doc or {}).get("custom_fields") or [], 
            amt_val,
            date_val,
            )

    api_req("PATCH", f"/api/documents/{doc_id}/", data=custom_fields_data)
#    log(f"Set extracted custom fields on doc {doc_id}: amount={amt_val}, date={date_val}")


    prediction = {
            "amount_pred": amt_val,
            "purchase_date_pred": date_val,
            "raw_amount_token": "12.3h",
            "raw_date_pred": "2025-01-02",
            }
    os.makedirs(PRED_DIR, exist_ok=True)
    pred_path = os.path.join(PRED_DIR, f"{doc_id}.json")

    with open(pred_path, "w") as f:
        json.dump(prediction, f)

#    log(f"Wrote prediction to {pred_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
