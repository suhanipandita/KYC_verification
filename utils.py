import streamlit as st
import cv2
import numpy as np
import re
import difflib
import gzip
import easyocr
import pytesseract
from pyzbar.pyzbar import decode
from supabase import create_client, Client

# Initialize Supabase
supabase: Client = None
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    if "YOUR_SUPABASE" not in SUPABASE_URL:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception:
    pass

# --- UPDATED LOGGING FUNCTION ---
def log_to_db(track, status, id_name, aadhar_name, qr_name, aadhar_number, score, forensic, result, meta_json):
    if supabase:
        try:
            data = {
                "track_type": track,
                "user_status": status,
                "extracted_name": id_name,         # Name from ID/Offer Letter
                "aadhar_name": aadhar_name,        # Name found on Aadhaar Card Text
                "qr_name": qr_name,                # Name from QR
                "aadhar_number": aadhar_number,    # 12-digit Number from OCR
                "face_match_score": float(score) if score else 0.0,
                "forensic_status": forensic,
                "final_result": result,
                "verification_meta": meta_json     # New JSON Format
            }
            supabase.table("verification_logs").insert(data).execute()
            return True
        except Exception as e:
            st.error(f"Database logging failed: {e}")
            return False
    return False

# --- 1. EXTRACT NAME FROM CARD (TEXT) ---
def check_name_on_card(image_path, target_name):
    """
    Scans the Aadhaar Card text (OCR) and checks if the 'target_name' (from QR)
    is present on the card.
    """
    if not target_name: return False, "QR Name Missing"

    # Normalize target name (Remove spaces, special chars)
    clean_target = re.sub(r'[^A-Z]', '', target_name.upper())

    # Helper to clean OCR text lines
    def clean(text): return re.sub(r'[^A-Z]', '', text.upper())

    # 1. Try EasyOCR
    try:
        reader = easyocr.Reader(['en'])
        results = reader.readtext(image_path, detail=0)
        for line in results:
            # Fuzzy match the line against the target name
            if difflib.SequenceMatcher(None, clean(line), clean_target).ratio() > 0.85:
                return True, line # Return the text we found that matched
    except: pass

    # 2. Try Tesseract
    try:
        img = cv2.imread(image_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray)
        for line in text.split('\n'):
            if difflib.SequenceMatcher(None, clean(line), clean_target).ratio() > 0.85:
                return True, line
    except: pass

    return False, "Not Found"

# --- 2. EXTRACT AADHAAR NUMBER ---
def smart_correct_digits(text):
    text = text.upper()
    corrections = {'O': '0', 'D': '0', 'Q': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'B': '8'}
    return "".join([corrections.get(c, c) for c in text])

def extract_aadhar_number_ocr(image_path):
    def find_uid(text):
        clean_text = smart_correct_digits(text)
        match = re.search(r'\b(\d{4}\s\d{4}\s\d{4})\b', clean_text)
        if match: return match.group(1).replace(" ", "")
        match_loose = re.search(r'\b(\d{12})\b', clean_text.replace(" ", ""))
        if match_loose: return match_loose.group(1)
        return None

    try:
        reader = easyocr.Reader(['en'])
        result = reader.readtext(image_path, detail=0)
        uid = find_uid(" ".join(result))
        if uid: return uid
    except: pass
    
    try:
        img = cv2.imread(image_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray, config='--psm 6')
        uid = find_uid(text)
        if uid: return uid
    except: pass
    return None

# --- 3. EXTRACT QR DATA ---
def decode_secure_qr(qr_data_str):
    try:
        data_int = int(qr_data_str)
        byte_len = (data_int.bit_length() + 7) // 8
        data_bytes = data_int.to_bytes(byte_len, 'big')
        decompressed_data = gzip.decompress(data_bytes)
        text_data = decompressed_data.decode("ISO-8859-1")
        parts = text_data.split("\xff")
        name = parts[3] if len(parts) > 3 else None
        return name
    except: return None

def extract_aadhar_qr_name(image_path):
    """Only returns the Name from the QR."""
    img = cv2.imread(image_path)
    if img is None: return None

    decoded_objects = decode(img)
    if not decoded_objects:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        decoded_objects = decode(gray)

    for obj in decoded_objects:
        try:
            raw_data = obj.data.decode("utf-8")
            # Old XML
            if "name=" in raw_data:
                match = re.search(r'name="([^"]+)"', raw_data)
                if match: return match.group(1)
            # Secure QR
            elif raw_data.isdigit():
                return decode_secure_qr(raw_data)
        except: continue
    return None

# --- 4. NAME COMPARISON ---
def verify_name_match(name1, name2):
    if not name1 or not name2: return 0.0, False
    n1 = re.sub(r'[^A-Z\s]', '', name1.upper()).strip()
    n2 = re.sub(r'[^A-Z\s]', '', name2.upper()).strip()
    n1_sorted = " ".join(sorted(n1.split()))
    n2_sorted = " ".join(sorted(n2.split()))
    score = difflib.SequenceMatcher(None, n1_sorted, n2_sorted).ratio() * 100
    return score, score >= 80