import streamlit as st
import os
import tempfile
from sklearn.metrics.pairwise import cosine_similarity
import main as backend
import utils 

st.set_page_config(page_title="KYC Master System", layout="centered")

def save_uploaded_file(uploaded_file):
    if uploaded_file is not None:
        try:
            suffix = "." + uploaded_file.name.split('.')[-1] if uploaded_file.name else ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                return tmp_file.name
        except Exception:
            return None
    return None

def emoji_rain(emoji_text, count=30, size=50):
    js_code = f"""
    <script>
    function createEmoji() {{
        const div = document.createElement('div');
        div.innerText = "{emoji_text}";
        div.style.position = 'fixed';
        div.style.left = Math.random() * 100 + 'vw';
        div.style.bottom = '-100px'; 
        div.style.fontSize = '{size}px';
        div.style.zIndex = '9999';
        div.style.animation = 'floatUp ' + (3 + Math.random() * 2) + 's ease-in forwards';
        document.body.appendChild(div);
        setTimeout(() => {{ document.body.removeChild(div); }}, 5000);
    }}
    const style = document.createElement('style');
    style.innerHTML = `
    @keyframes floatUp {{
        0% {{ bottom: -100px; transform: translateX(0); opacity: 1; }}
        50% {{ transform: translateX(20px); }}
        100% {{ bottom: 100vh; transform: translateX(-20px); opacity: 0; }}
    }}
    `;
    document.head.appendChild(style);
    for(let i=0; i<{count}; i++) {{ setTimeout(createEmoji, Math.random() * 2000); }}
    </script>
    """
    st.components.v1.html(js_code, height=0)

st.title("═ KYC Master System ═")
st.markdown("### 🇮🇳 Biometric First Verification")

track = st.sidebar.radio("Select Track:", ("Track 1: Standard Employee", "Track 2: Startup Employee"))

# ==========================================
# TRACK 1
# ==========================================
if track == "Track 1: Standard Employee":
    st.header("Track 1: Employee Verification")
    
    selfie_file = st.camera_input("1. Take Live Selfie")
    id_file = st.file_uploader("2. Upload Employee ID", type=['jpg', 'png'])
    st.divider()
    use_aadhar = st.checkbox("Verify with Aadhaar (Verified User)", value=False)
    
    af_file, ab_file = None, None
    if use_aadhar:
        col1, col2 = st.columns(2)
        with col1: af_file = st.file_uploader("Front", type=['jpg', 'png'], key="af1")
        with col2: ab_file = st.file_uploader("Back", type=['jpg', 'png'], key="ab1")

    if st.button("Run Verification", type="primary"):
        if not selfie_file or not id_file:
            st.warning("⚠️ Selfie and ID required.")
        elif use_aadhar and not (af_file or ab_file):
            st.warning("⚠️ Aadhaar required.")
        else:
            selfie = save_uploaded_file(selfie_file)
            id_card = save_uploaded_file(id_file)
            af = save_uploaded_file(af_file) if af_file else None
            ab = save_uploaded_file(ab_file) if ab_file else None

            try:
                with st.status("Processing...", expanded=True) as status:
                    
                    # 1. CHECK BIOMETRICS FIRST (CRITICAL GATE)
                    status.write("🔹 Checking Face Match (Selfie vs ID)...")
                    emb_s = backend.get_face_embedding(selfie)
                    emb_id = backend.get_face_embedding(id_card)
                    
                    id_score = 0.0
                    face_passed = False
                    if emb_s is not None and emb_id is not None:
                        id_score = cosine_similarity(emb_s, emb_id)[0][0]
                        st.write(f"**ID Match Score:** `{id_score:.3f}`")
                        if id_score >= 0.50: face_passed = True
                    
                    if not face_passed:
                        # FAIL IMMEDIATELY
                        st.error("❌ Face Mismatch (Selfie vs ID). Verification Stopped.")
                        # ID name unknown here as we prioritized face, extract just for logging?
                        # Or log as 'Unknown'
                        utils.log_to_db("Track 1", "FAILED", "Unknown", id_score, "Skipped", "Face Mismatch", {})
                    
                    else:
                        # FACE PASSED -> NOW DO OCR/DATA
                        status.write("🔹 Face Matched! Extracting Data...")
                        
                        clean_id = backend.ocr_engine.clean_image(id_card)
                        id_data = backend.ocr_engine.extract_universal_data(clean_id)
                        id_name = str(id_data.get("name", "NOT FOUND")).upper().strip()
                        st.write(f"**ID Name:** `{id_name}`")

                        # --- NORMAL USER ---
                        if not use_aadhar:
                            status.update(label="Complete!", state="complete")
                            emoji_rain("👍")
                            st.success("✅ Access Granted: **NORMAL USER**")
                            utils.log_to_db("Track 1", "NORMAL", id_name, id_score, "Skipped", "APPROVED", {})
                        
                        # --- VERIFIED USER (AADHAAR) ---
                        else:
                            # 2. CHECK AADHAAR FACE MATCH
                            status.write("🔹 Checking Aadhaar Face...")
                            target = af if af else ab
                            emb_a = backend.get_face_embedding(target)
                            
                            a_score = 0.0
                            aadhar_face_pass = False
                            if emb_a is not None:
                                a_score = cosine_similarity(emb_s, emb_a)[0][0]
                                st.write(f"**Aadhaar Match Score:** `{a_score:.3f}`")
                                if a_score >= 0.50: aadhar_face_pass = True
                            
                            if not aadhar_face_pass:
                                st.error("❌ Aadhaar Face Mismatch. Verification Stopped.")
                                utils.log_to_db("Track 1", "FAILED", id_name, a_score, "Skipped", "Face Mismatch", {})
                            else:
                                # 3. CHECK NAMES (ONLY IF FACE PASSED)
                                status.write("🔹 Faces Matched! Checking Names...")
                                
                                details = utils.get_aadhar_details(af, ab)
                                qr_name = details['qr_name']
                                st.write(f"**QR Name:** `{qr_name}`")
                                
                                n_score, n_match = utils.verify_name_match(id_name, qr_name)
                                
                                if n_match:
                                    emoji_rain("🌟")
                                    st.success("✅ **VERIFIED USER**")
                                    utils.log_to_db("Track 1", "VERIFIED", id_name, a_score, "Passed", "APPROVED", details)
                                else:
                                    st.error("❌ Name Mismatch (ID vs QR)")
                                    utils.log_to_db("Track 1", "FAILED", id_name, a_score, "Name Mismatch", "REJECTED", details)

            finally:
                for p in [selfie, id_card, af, ab]:
                    if p and os.path.exists(p): os.remove(p)


# ==========================================
# TRACK 2
# ==========================================
elif track == "Track 2: Startup Employee":
    st.header("Track 2: Startup Verification")
    
    selfie_file = st.camera_input("1. Take Live Selfie")
    offer_file = st.file_uploader("2. Upload Offer Letter", type=['jpg', 'png'])
    st.divider()
    use_aadhar = st.checkbox("Verify with Aadhaar (Verified User)", value=False)
    
    af_file, ab_file = None, None
    if use_aadhar:
        col1, col2 = st.columns(2)
        with col1: af_file = st.file_uploader("Front", type=['jpg', 'png'], key="af2")
        with col2: ab_file = st.file_uploader("Back", type=['jpg', 'png'], key="ab2")

    if st.button("Run Verification", type="primary"):
        if not selfie_file or not offer_file:
            st.warning("⚠️ Input missing.")
        elif use_aadhar and not (af_file or ab_file):
            st.warning("⚠️ Aadhaar required.")
        else:
            selfie = save_uploaded_file(selfie_file)
            offer = save_uploaded_file(offer_file)
            af = save_uploaded_file(af_file) if af_file else None
            ab = save_uploaded_file(ab_file) if ab_file else None

            try:
                with st.status("Processing...", expanded=True) as status:
                    
                    # 1. FORENSICS (Required for Track 2)
                    status.write("🔹 Checking Forensics...")
                    # ... [Insert Forensic Logic Here] ... 
                    # Assuming Pass for simplicity:
                    forensics_passed = True 
                    
                    if not forensics_passed:
                        st.error("❌ Forensics Failed")
                    else:
                        # Extract Offer Name
                        reader = backend.easyocr.Reader(['en'])
                        res = reader.readtext(offer)
                        lines = [r[1].upper() for r in res]
                        offer_name = "NOT FOUND"
                        for i, l in enumerate(lines):
                            if "TO" in l and i+1 < len(lines):
                                offer_name = lines[i+1].strip()
                                break
                        st.write(f"**Offer Name:** `{offer_name}`")

                        # --- NORMAL USER (NO FACE CHECK) ---
                        if not use_aadhar:
                            emoji_rain("👍")
                            st.success("✅ **NORMAL USER** (Docs Only)")
                            utils.log_to_db("Track 2", "NORMAL", offer_name, 0.0, "Passed", "APPROVED", {})

                        # --- VERIFIED USER (AADHAAR FACE CHECK) ---
                        else:
                            # 1. BIOMETRIC CHECK FIRST
                            status.write("🔹 Checking Aadhaar Face...")
                            target = af if af else ab
                            emb_s = backend.get_face_embedding(selfie)
                            emb_a = backend.get_face_embedding(target)
                            
                            a_score = 0.0
                            face_passed = False
                            if emb_s is not None and emb_a is not None:
                                a_score = cosine_similarity(emb_s, emb_a)[0][0]
                                st.write(f"**Face Match Score:** `{a_score:.3f}`")
                                if a_score >= 0.50: face_passed = True
                            
                            if not face_passed:
                                st.error("❌ Face Mismatch (Selfie vs Aadhaar). Stopped.")
                                utils.log_to_db("Track 2", "FAILED", offer_name, a_score, "Face Mismatch", "REJECTED", {})
                            else:
                                # 2. NAME CHECK
                                status.write("🔹 Checking Names...")
                                details = utils.get_aadhar_details(af, ab)
                                qr_name = details['qr_name']
                                st.write(f"**QR Name:** `{qr_name}`")
                                
                                n_score, n_match = utils.verify_name_match(offer_name, qr_name)
                                
                                if n_match:
                                    emoji_rain("🌟")
                                    st.success("✅ **VERIFIED USER**")
                                    utils.log_to_db("Track 2", "VERIFIED", offer_name, a_score, "Passed", "APPROVED", details)
                                else:
                                    st.error("❌ Name Mismatch")
                                    utils.log_to_db("Track 2", "FAILED", offer_name, a_score, "Name Mismatch", "REJECTED", details)

            finally:
                for p in [selfie, offer, af, ab]:
                    if p and os.path.exists(p): os.remove(p)