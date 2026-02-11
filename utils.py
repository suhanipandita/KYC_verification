import streamlit as st
import cv2
import numpy as np
import re
import difflib
import gzip
import easyocr
import pytesseract
from pyzbar.pyzbar import decode
from pymongo import MongoClient
import certifi
from datetime import datetime

# --- MONGODB CONNECTION SETUP ---
# We use st.cache_resource so we don't reconnect on every rerun
@st.cache_resource
def get_mongo_client():
    try:
        uri = st.secrets["mongodb"]["uri"]
        # ca=certifi.where() is critical for SSL connections on some networks
        client = MongoClient(uri, tlsCAFile=certifi.where())
        # Test connection
        client.admin.command('ping')
        return client
    except Exception as e:
        st.error(f"❌ MongoDB Connection Error: {e}")
        return None

def log_to_db(track, status, id_name, score, forensic, result, meta_json):
    """Logs verification attempts to MongoDB Atlas."""
    client = get_mongo_client()
    if client:
        try:
            db = client["kyc_database"]        # Your Database Name
            collection = db["verification_logs"] # Your Collection (Table) Name
            
            # Safe extraction of values
            aadhar_name = meta_json.get("qr_name", "N/A")
            aadhar_num = meta_json.get("aadhar_number", "N/A")
            
            # Prepare the document (No need to stringify JSON for MongoDB!)
            log_entry = {
                "timestamp": datetime.now(),
                "track_type": track,
                "user_status": status,
                "extracted_name": id_name,
                "aadhar_name": aadhar_name,
                "qr_name": aadhar_name,
                "aadhar_number": aadhar_num,
                "face_match_score": float(score) if score else 0.0,
                "forensic_status": forensic,
                "final_result": result,
                "verification_meta": meta_json  # MongoDB stores this as a real Object/Dict
            }
            
            collection.insert_one(log_entry)
            return True
        except Exception as e:
            print(f"MongoDB Write Error: {e}") 
            return False
    return False

# --- KEEPING YOUR EXISTING EXTRACTORS (No Changes Needed Here) ---
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

def decode_secure_qr(qr_data_str):
    try:
        data_int = int(qr_data_str)
        byte_len = (data_int.bit_length() + 7) // 8
        data_bytes = data_int.to_bytes(byte_len, 'big')
        decompressed_data = gzip.decompress(data_bytes)
        text_data = decompressed_data.decode("ISO-8859-1")
        parts = text_data.split("\xff")
        name = parts[3] if len(parts) > 3 else None
        return name, "SECURE_HIDDEN"
    except: return None, None

def extract_aadhar_qr(image_path):
    img = cv2.imread(image_path)
    if img is None: return None, None
    decoded_objects = decode(img)
    if not decoded_objects:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        decoded_objects = decode(gray)

    for obj in decoded_objects:
        try:
            raw_data = obj.data.decode("utf-8")
            if "uid=" in raw_data:
                match = re.search(r'name="([^"]+)"', raw_data)
                uid_match = re.search(r'uid="(\d+)"', raw_data)
                name = match.group(1) if match else None
                uid = uid_match.group(1) if uid_match else None
                return name, uid
            elif raw_data.isdigit():
                return decode_secure_qr(raw_data)
        except: continue
    return None, None

def get_aadhar_details(front_path, back_path):
    qr_name, qr_num = None, None
    if back_path: qr_name, qr_num = extract_aadhar_qr(back_path)
    if not qr_name and front_path: qr_name, qr_num = extract_aadhar_qr(front_path)

    ocr_num = None
    if front_path: ocr_num = extract_aadhar_number_ocr(front_path)
    
    final_number = ocr_num if ocr_num else (qr_num if qr_num else "Not Found")
    
    return {
        "qr_name": qr_name,
        "aadhar_number": final_number,
        "ocr_raw": ocr_num
    }

def verify_name_match(name1, name2):
    if not name1 or not name2: return 0.0, False
    n1 = re.sub(r'[^A-Z\s]', '', name1.upper()).strip()
    n2 = re.sub(r'[^A-Z\s]', '', name2.upper()).strip()
    n1_sorted = " ".join(sorted(n1.split()))
    n2_sorted = " ".join(sorted(n2.split()))
    score = difflib.SequenceMatcher(None, n1_sorted, n2_sorted).ratio() * 100
    return score, score >= 80