from flask import Flask, request, jsonify
import requests
import sys
import json
import os
from urllib.parse import urlparse
import time
import threading
from llama_cpp import Llama
from prep_ocr import trim_ocr, parse_prediction

MODEL_PATH = os.environ.get("LLM_MODEL_PATH", "/models/model.gguf")
N_THREADS = os.environ.get("LLM_N_THREADS")
N_THREADS = int(N_THREADS) if N_THREADS else None

PRED_DIR = "/pred_cache"
LOG_DIR = os.path.join("/tmp", "paperless_test_logs")


API_ROOT = os.environ["PAPERLESS_API_URL"]
API_KEY = os.environ["PAPERLESS_API_KEY"]


session = requests.Session()
session.headers.update({
    "Authorization": f"Token {API_KEY}",
    "Accept": "application/json; version=6",
    })


app = Flask(__name__)

_llm = None
_llm_lock = threading.Lock()


def get_llm():
    global _llm
    if _llm is not None:
        return _llm
    with _llm_lock:
        if _llm is None:
            _llm = Llama(model_path = MODEL_PATH, n_ctx=2048, n_threads=N_THREADS)
    return _llm


def get_field_map():
    """Request id nums for custom fields {name: id}"""
    url = API_ROOT + "/api/custom_fields/"
    # print(f"url: {url}", file=sys.stdout, flush=True)
    for attempt in range(10):
        try:   
            res = session.get(url)
            res.raise_for_status()
            fields = res.json().get('results')
            print(f"got field map response: \n{fields}")
            id_dict = {f["name"]: f["id"] for f in fields}
            return id_dict
        except requests.RequestException as e:
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


def get_doc(doc_id: int) -> dict:
    url = API_ROOT + f"/api/documents/{doc_id}/"
    res = session.get(url)
    res.raise_for_status()
    return res.json()

def extract_amt_date(doc: dict):
    amount = None
    date = None

    for cf in doc.get("custom_fields", []):
        field_id = cf.get("field")
        if field_id == AMOUNT_ID:
            amount = cf.get("value")
        elif field_id == DATE_ID:
            date = cf.get("value")
    return amount, date

def log(msg: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, "post_consume.log"), "a") as f:
        f.write(msg + "\n")

def llm_log(msg: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, "llm.log"), "a") as f:
        f.write(str(msg) + "\n")

@app.post("/paperless-webhook")
def paperless_webhook():
    data = request.get_json(force=True, silent=True) or {}
    doc_url = data.get("url")

    try:
        path = urlparse(doc_url).path
        doc_id_str = path.rstrip("/").split("/")[-1]
        doc_id = int(doc_id_str)
    except Exception as e:
        print(f"Could not parse doc_id from doc_url={doc_url}: {e}", file=sys.stdout, flush=True)
        return jsonify({"status": "bad_doc_url"}), 400


    print(f"Webhook for document_id={doc_id}", file=sys.stdout, flush=True)
    print("== Got request ==", file=sys.stdout, flush=True)
    print(json.dumps(data, indent=4), file=sys.stdout, flush=True)

    if doc_id is None:
        print("No document_id in payload, ignoring", file=sys.stdout, flush=True)
        return jsonify({"status": "no_doc_id"}), 400

    pred_path = os.path.join(PRED_DIR, f"{doc_id}.json")
    if not os.path.exists(pred_path):
        print(f"No prediction file for doc {doc_id}", file=sys.stdout, flush=True)
        return jsonify({"status": "no_prediction"}), 200

    try:
        with open(pred_path, "r", encoding="utf-8") as f:
            prediction = json.load(f)
        doc = get_doc(doc_id)
        amount, p_date = extract_amt_date(doc)

    except Exception as e:
        print(f"Error reading prediction for doc {doc_id}: {e}", file=sys.stdout, flush=True)
        return jsonify({"status": "error_reading_prediction"}), 500
    
#    log(f"Doc {doc_id}: pred_amount={prediction.get('amount_pred')} ")
#    log(f"actual_amount={amount} pred_date={prediction.get('purchase_date_pred')} ")
#    log(f"actual_date={p_date}")
    

    print(f"Wrote fake correction entry for doc {doc_id}", file=sys.stdout, flush=True)
    return jsonify({"status": "ok"})


TEMPLATE = """{
            "amount": "dollar value string, total paid, with 2 decimals, e.g. 23.45.",
            "purchase_date": "string, purchase date in YYYY-MM-DD"
            }"""

#def build_prompt_generic(ocr_text: str) -> str:
#    return f"""You are a strict JSON extraction engine.
#    Given the OCR text of a receipt, extract the following fields:
#    - amount: the final total paid (including tax), formatted as a number with 2 decimals, e.g. "23.45".
#    - purchase_date: the purchase date, formatted as "YYYY-MM-DD".
#    Here is the JSON schema you MUST follow:
#    {TEMPLATE}
#    Fill in the values based on the text below. If you cannot find a field, set its value to null.
#    Return ONLY a single JSON object, no explanations.
#    Receipt text:
#    {ocr_text}
#    """

def build_prompt_generic(ocr_text: str) -> str:
    return f"""Given the OCR text of a receipt, extract the following fields:
    - amount: the final total paid (including tax), formatted as a number with 2 decimals, e.g. "23.45".
    - purchase_date: the purchase date, formatted as "YYYY-MM-DD".
    The date in the OCR text may be in any number of formats: YYYY-MM-DD, MM-DD-YYYY, MM/DD/YYYY, etc. 
    Separators for the date in the ocr text may be "-", "/", ".", or any common date format. Month and day
    may or may not have leading 0. Year may be in 2 or 4 digit format. For 2 digit years, assume the first 2
    digits are "20". Please format the extracted date in your response as "YYYY-MM-DD"
    Here is the JSON schema you MUST follow:
    {TEMPLATE}
    Fill in the values based on the text below. If you cannot find a field, set its value to null (no quotes).
    Return ONLY a single JSON object, no explanations.
    Receipt text:
    {ocr_text}
    """

def build_prompt2(ocr_text: str) -> str:
    return f"""
        Your entire response MUST be a single JSON object, with nothing before it and nothing after it.

        The JSON object must have exactly these keys:
        - "amount": the final total paid (including tax), as a string with 2 decimals, e.g. "23.45", or null if unknown.
        - "purchase_date": the purchase date as a string in "YYYY-MM-DD" format, or null if unknown.

        Example:

        Input:
        '''
        Total: $24.19
        Date: 11/26/25
        '''

        Correct output:
        {{"amount": "24.19", "purchase_date": "2025-11-26"}}

        If the date or amount cannot be determined, use null like:
        {{"amount": "24.19", "purchase_date": null}}

        If the ocr engine made an error like:
        '''
        Total: $139.7h
        Date: I2/06/2023
        '''
        Please make your best guess for the incorrectly read digit:
        {{"amount": "139.75", "purchase_date": "2023-12-06"}}

        Notes: Total may be called Amount Due or similar. Look for the largest $ amount if purchase amount is unclear.

        Now process this receipt:

        Input:
        '''
        {ocr_text}
        '''

    """


def null_to_none(val):
    if val is None:
        return None
    if isinstance(val, str) and val.strip().lower() in ("null", "none", ""):
        return None
    return val

@app.post("/extract")
def extract():
    data = request.get_json(force=True, silent=True) or {}
    ocr = data.get("ocr", "") or ""

    print(f"[extract] got ocr data with length: {len(ocr)}", file=sys.stdout, flush=True)

    if not ocr.strip():
        return jsonify({"amount": None, "purchase_date": None}), 200

    llm = get_llm()

    trimmed = trim_ocr(ocr)
    print(f"[extract] trimmed ocr length: {len(trimmed)}", file=sys.stdout, flush=True)

    prompt = build_prompt2(trimmed)

    llm_log("prompt:")
    llm_log(prompt)

#    res = llm(
#            prompt,
#            max_tokens=128,
#            temperature=0.0,
#            )

    res = llm.create_chat_completion(
            messages=[
                {"role": "system", 
                 "content": "You are a strict JSON extraction engine. Always respond with a JSON object."},
                {"role": "user", 
                 "content": prompt},
                ],
            max_tokens=128,
            temperature=0.0,
            response_format={"type": "json_object"},
            )

    
    llm_log("prediction:")
    llm_log(res)

    parsed = parse_prediction(res["choices"][0]["message"]["content"])

    amount = null_to_none(parsed.get("amount", "0.00"))
    date = null_to_none(parsed.get("purchase_date", "1970-01-01"))

    return jsonify({"amount": amount, "purchase_date": date}), 200
