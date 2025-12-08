import re
import sys
import json

MIN_TRIM = 20
SMALL_LINE_CHAR = 40

def _drop_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if len(stripped) <= 1:
        return True
    
    alpha_numeric = sum(c.isalnum() for c in stripped)
    return alpha_numeric <= 1

def trim_ocr(ocr: str) -> str:
    print("######[Trimming OCR]######", file=sys.stdout, flush=True)
    
    raw_lines = ocr.splitlines()
    lines = [ln.rstrip() for ln in raw_lines if not _drop_line(ln)]
    
    line_len = len(lines)
    print(f"[trim_ocr] num lines: {line_len}", file=sys.stdout, flush=True)

    if line_len == 0:
        print("[trim_ocr] got 0 lines, returning blank", file=sys.stdout, flush=True)
        return ""

    if line_len <= MIN_TRIM:
        print("[trim_ocr] not enough lines to bother trimming, returning unchanged", file=sys.stdout, flush=True)
        return "\n".join(lines)

    keep: set[int] = set()

    for i, line in enumerate(lines):
        if i in keep:
            continue
        if not line:
            continue

        has_digit = any(c.isdigit() for c in line)
        is_short = len(line) <= SMALL_LINE_CHAR

        if has_digit or is_short:
            keep.add(i)
    
    print(f"[trim_ocr] keeping {len(keep)} lines of {line_len}", file=sys.stdout, flush=True)

    kept_indices = sorted(keep)

    trimmed_lines: list[str] = []
    last_idx = None
    for idx in kept_indices:
        l = lines[idx]
        if not l:
            continue
        if last_idx is not None and idx > last_idx + 1:
            trimmed_lines.append("...")
        trimmed_lines.append(l)
        last_idx = idx
    return "\n".join(trimmed_lines)


def parse_prediction(prediction: str, doc_id=None) -> dict:
    print(f"[parse_prediction] got prediction to parse: `{prediction!r}`", file=sys.stdout, flush=True)
    text = prediction.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = "```".join(parts[1:-1]).strip()

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        return {}
    except Exception as e:
        print(f"first parse failed: {e}", file=sys.stdout, flush=True)
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(text[start:end+1])
                if isinstance(obj, dict):
                    return obj
                return {}
            except Exception as e:
                print(f"second parse failed {e}", file=sys.stdout, flush=True)
                print(f"unable to parse prediction: {text[start:end+1]}", file=sys.stdout, flush=True)

    print(f"[helper] Could not parse JSON for doc {doc_id}, text={prediction!r}", file=sys.stdout, flush=True)
    return {}
