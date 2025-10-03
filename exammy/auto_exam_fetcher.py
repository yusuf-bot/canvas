#!/usr/bin/env python3
"""
auto_exam_fetcher.py
One-liner example:
    python auto_exam_fetcher.py 9618 2023 s 32
"""

import os
import re
import sys
import time
import tempfile
import subprocess
import requests
from pathlib import Path
from typing import Optional, Dict, Any

import io
import base64
from mistralai import Mistral

# ===================== CONFIG =====================
import itertools
import random

# ===================== CONFIG =====================
API_KEYS = [
    "vxijWkbWvCYhKEHkZZgrmCvRgdrZ0sXs",  # key1
    "SG6Vd7x0DzriFciNXgXX2fmNDHLBlchk"
    # Add more if needed
]
MODEL = "mistral-large-latest"
OCR_MODEL = "mistral-ocr-latest"

# Use an infinite cyclic iterator for round-robin access
_api_cycle = itertools.cycle(API_KEYS)

# How long to wait between each Mistral call (seconds)
REQUEST_DELAY = 3


def get_client():
    """Return a Mistral client with the next rotated API key."""
    key = next(_api_cycle)
    return Mistral(api_key=key)


SYSTEM_PROMPT = """You are an intelligent parser that extracts **complete** information from OCR-scanned CAIE question papers (QP) and mark schemes (MS) and returns a fully-populated JSON payload.

1. Scope  
   • QP → extract every **entire** question, sub-question, table, diagram, figure, graph, or code block exactly as it appears.  
   • MS → extract every **entire** mark point, answer line, acceptable response, sample code, formula, or diagram.  
   • Insert (if provided) → treat only as background context; copy verbatim into `"context"` but **never** let it alter questions or answers.

2. Completeness rules  
   • If a question contains a **table**, include the **full table** in Markdown.  
   • If it contains a **diagram/graph**, add a concise but informative **description** plus a simple ASCII or Unicode representation that conveys the structure (e.g. axes, labels, trend).  
        Example:  
        ```  
        [Diagram: quadratic graph y = ax²+bx+c opening upward, vertex (-b/2a, -Δ/4a), y-intercept c]  
        ```
   • If you cannot draw an exact replica, provide a **representative sketch** (ASCII/Unicode) so another model can still understand the visual.  
   • Never truncate formulas, code snippets, or long mark-scheme answers.

3. JSON structure (strictly return only valid JSON)  
{
  "subject_code": "<from cover>",
  "paper_code": "<from cover>",
  "exam_session": "<Summer|Winter|March>",
  "exam_year": "<4-digit>",
  "context": "<cleaned insert text or 'no insert provided'>",
  "questions": [
    {
      "question_number": "1",
      "subquestions": [
        {
          "subquestion_label": "a(i)",
          "question_text": "<full text including tables/diagrams>",
          "question_type": "<mcq|short_answer|long_answer|table_completion|calculation|code_trace|etc>",
          "marks": <int>,
          "answer": "<full mark-scheme answer including any tables/diagrams>",
          "answer_conditions": ["<full mark-point text>", "..."]
        }
      ]
    }
  ]
}

Return only the JSON object. No commentary or markdown fences outside the JSON."""

client = get_client()

# ===================== UTILITIES =====================
def _url(subj: str, yr: str, ssn: str, var: str, suffix: str) -> str:
    """
    suffix = 'qp' | 'ms' | 'in'
    returns e.g. https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/9618_s23_qp_32.pdf
    """
    return (
        f"https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/"
        f"{subj}_{ssn}{yr[-2:]}_{suffix}_{var}.pdf"
    )

def _download(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code != 200 or 'application/pdf' not in r.headers.get('content-type', ''):
            return False
        dest.write_bytes(r.content)
        # quick magic-byte check
        return dest.read_bytes()[:4] == b'%PDF'
    except Exception:
        return False


def ocr_whole_pdf(pdf_path: Path) -> str:
    """OCR the entire PDF at once using Mistral OCR."""
    try:
        client = get_client()
        
        print(f"Processing entire PDF: {pdf_path.name}")
        
        # Step 1: Upload the PDF file
        print(f"  - Uploading {pdf_path.name}...")
        uploaded_pdf = client.files.upload(
            file={
                "file_name": pdf_path.name,
                "content": open(pdf_path, "rb"),
            },
            purpose="ocr"
        )
        
        # Step 2: Get signed URL
        print(f"  - Getting signed URL...")
        signed_url = client.files.get_signed_url(file_id=uploaded_pdf.id)
        
        # Step 3: Process OCR
        print(f"  - Running OCR...")
        resp = client.ocr.process(
            model=OCR_MODEL,
            document={
                "type": "document_url",
                "document_url": signed_url.url,
            },
            include_image_base64=False,
        )
        
        # Step 4: Combine all pages' markdown content
        full_text = ""
        if resp.pages:
            for i, page in enumerate(resp.pages):
                page_text = page.markdown.strip() if page.markdown else ""
                full_text += f"\n--- Page {i+1} ---\n{page_text}\n"
        
        # Step 5: Clean up - delete the uploaded file
        try:
            client.files.delete(file_id=uploaded_pdf.id)
            print(f"  - Cleaned up uploaded file")
        except Exception as cleanup_error:
            print(f"  - Warning: Could not delete uploaded file: {cleanup_error}")
        
        time.sleep(REQUEST_DELAY)
        return full_text.strip()
        
    except Exception as e:
        print(f"Error OCRing PDF {pdf_path.name}: {e}")
        return f"[Error processing PDF: {e}]"


def clean_insert_text(raw: str) -> str:
    """very light cleaning"""
    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln and not re.match(r"page\s+\d+ of \d+", ln, re.I)]
    return "\n".join(lines).strip()


# ===================== CORE =====================
def fetch_and_process(subj: str, yr: str, ssn: str, var: str, out_dir: str = "output_json") -> Dict[str, Any]:
    """
    subj: 9618
    yr  : 2023
    ssn : s | w | m
    var : 32
    """
    Path(out_dir).mkdir(exist_ok=True)
    base_name = f"{subj}_{ssn}{yr[-2:]}_{var}"

    # ---- download files ----
    files = {}
    tmp_dir = Path(tempfile.mkdtemp())
    for suffix in ("qp", "ms", "in"):
        url = _url(subj, yr, ssn, var, suffix)
        local = tmp_dir / f"{suffix}.pdf"
        print(f"Checking {suffix.upper()} => {url}")
        if _download(url, local) and local.stat().st_size > 0:
            files[suffix] = local
            print(f"  ✓ saved {local}")
        else:
            print(f"  ✗ not found / empty")
            if local.exists():
                local.unlink()

    qp_path = files.get("qp")
    ms_path = files.get("ms")
    in_path = files.get("in")

    if not qp_path or not ms_path:
        raise FileNotFoundError("QP or MS missing – aborting.")

    # ---- OCR phase - Process entire PDFs at once ----
    print("\nOCRing entire QP...")
    qp_text = ocr_whole_pdf(qp_path)
    
    print("OCRing entire MS...")
    ms_text = ocr_whole_pdf(ms_path)
    
    in_text = ""
    if in_path:
        print("OCRing entire INSERT...")
        in_text = clean_insert_text(ocr_whole_pdf(in_path))

    # ---- LLM structuring ----
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"CONTEXT (Insert):\n{in_text or 'no context required'}\n\n"
                f"QUESTION PAPER TEXT:\n{qp_text}\n\n"
                f"MARK SCHEME TEXT:\n{ms_text}"
            ),
        },
    ]
    print("Parsing with Mistral …")
    client = get_client()
    chat_resp = client.chat.complete(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"},
    )
    structured_json = chat_resp.choices[0].message.content
    time.sleep(REQUEST_DELAY)

    # ---- save ----
    json_file = Path(out_dir) / f"{base_name}.json"
    json_file.write_text(structured_json, encoding="utf-8")
    print(f"Saved => {json_file}")
    
    # Clean up temporary files
    try:
        import shutil
        shutil.rmtree(tmp_dir)
    except:
        pass
    
    return {"json_path": str(json_file), "data": structured_json}


# ===================== CLI =====================
if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python auto_exam_fetcher.py <subject> <year> <season> <variant>")
        print(" e.g.: python auto_exam_fetcher.py 9618 2023 s 32")
        sys.exit(1)

    subj, yr, ssn, var = sys.argv[1:]
    fetch_and_process(subj, yr, ssn, var)
