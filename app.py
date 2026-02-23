import streamlit as st
import os
import re
from PIL import Image, ImageEnhance, ImageOps
import io
import sys

# --- LIBRARIES FOR OCR ---
try:
    import pytesseract
    if sys.platform.startswith('win'):
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    OCR_AVAILABLE = True
except:
    OCR_AVAILABLE = False

# --- PAGE CONFIG ---
st.set_page_config(page_title="Auto Photo Saver (Batch Pro)", page_icon="📸", layout="wide")

st.title("📸 Auto Photo & Passport Saver (Batch Pro)")
st.markdown("Har passenger ka Passport aur Photo uske makhsoos box mein upload karein taake koi data mix na ho. Yeh 100% Full Code hai.")

# --- HELPER: CLEAN NAME GARBAGE ---
def clean_name_garbage(text):
    if not text:
        return ""
    # Sirf A-Z aur spaces allow karein
    text = re.sub(r'[^A-Z ]', '', text.upper())
    # End mein aane walay faltu OCR characters ko saaf karein (jaise KKKK, SSSS)
    text = re.sub(r'(\s+[KCSXZE]+)+$', '', text)
    text = re.sub(r'[KCSXZE]{3,}$', '', text)
    # Faltu spaces khatam karein
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- HELPER: MRZ DATE FORMATTER ---
def format_mrz_date(raw_date):
    if not raw_date or not raw_date.isdigit() or len(raw_date) != 6:
        return ""
    yy, mm, dd = raw_date[0:2], raw_date[2:4], raw_date[4:6]
    months = {"01":"JAN", "02":"FEB", "03":"MAR", "04":"APR", "05":"MAY", "06":"JUN", 
              "07":"JUL", "08":"AUG", "09":"SEP", "10":"OCT", "11":"NOV", "12":"DEC"}
    month_str = months.get(mm, mm)
    return f"{dd}{month_str}{yy}"

# --- HELPER: FULL PASSPORT EXTRACTOR (DUAL SCAN) ---
def parse_passport_data_perfect(image):
    details = {
        'Given Name': '', 'Surname': '', 'Passport': '', 
        'DOB': '', 'Expiry': '', 'CNIC': '', 
        'Father Name': '', 'Gender': 'M'
    }
    
    width, height = image.size
    
    # ==========================================
    # SCAN 1: TOP HALF (For CNIC & Father Name)
    # ==========================================
    top_crop = image.crop((0, 0, width, int(height * 0.70)))
    top_resized = top_crop.resize((top_crop.width * 2, top_crop.height * 2), Image.Resampling.LANCZOS)
    top_gray = ImageOps.grayscale(top_resized)
    top_enh = ImageEnhance.Contrast(top_gray).enhance(2.0)
    
    top_text = pytesseract.image_to_string(top_enh).upper()
    
    # 1. Extract CNIC
    cnic_matches = re.findall(r'\b(\d{5})[-\s]?(\d{7})[-\s]?(\d)\b', top_text)
    if cnic_matches:
        details['CNIC'] = f"{cnic_matches[0][0]}-{cnic_matches[0][1]}-{cnic_matches[0][2]}"
        
    # 2. Extract Father / Husband Name
    lines = top_text.split('\n')
    for i, line in enumerate(lines):
        if re.search(r'(FATHER|HUSBAND|FATH|HUSB)', line):
            for j in range(1, 4):
                if i + j < len(lines):
                    cand = re.sub(r'[^A-Z ]', '', lines[i+j]).strip()
                    ignore_words = ["DATE", "BIRTH", "SEX", "PLACE", "NATIONALITY", "PASSPORT", "AUTHORITY", "PAKISTAN", "KARACHI", "ISSUING", "OF", "NAME", "REPUBLIC", "M", "F"]
                    if len(cand) > 3 and not any(w in cand for w in ignore_words):
                        details['Father Name'] = clean_name_garbage(cand)
                        break
            if details['Father Name']:
                break

    # ==========================================
    # SCAN 2: BOTTOM HALF (MRZ strict parsing)
    # ==========================================
    bot_crop = image.crop((0, int(height * 0.60), width, height))
    bot_resized = bot_crop.resize((bot_crop.width * 2, bot_crop.height * 2), Image.Resampling.LANCZOS)
    bot_gray = ImageOps.grayscale(bot_resized)
    bot_enh = ImageEnhance.Contrast(bot_gray).enhance(2.5)
    
    # Strict Whitelist to block KKKKK garbage
    mrz_config = r'-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789< --psm 6'
    mrz_text = pytesseract.image_to_string(bot_enh, config=mrz_config).upper()
    
    clean_text = mrz_text.replace(" ", "") 
    
    # Parse MRZ Line 2 (Passport, DOB, Gender, Expiry)
    mrz2_pattern = r'([A-Z0-9<]{8,9})[0-9<][A-Z<]{3}(\d{6})[0-9<]([MF<])(\d{6})'
    mrz2_match = re.search(mrz2_pattern, clean_text)
    
    if mrz2_match:
        details['Passport'] = mrz2_match.group(1).replace('<', '').replace('O', '0')
        details['DOB'] = format_mrz_date(mrz2_match.group(2))
        gender_char = mrz2_match.group(3)
        details['Gender'] = gender_char if gender_char in ['M', 'F'] else 'M'
        details['Expiry'] = format_mrz_date(mrz2_match.group(4))
        
    # CNIC from MRZ fallback
    if not details['CNIC']:
        cnic_mrz_match = re.search(r'\d{6}[0-9<](\d{13})', clean_text)
        if cnic_mrz_match:
            c = cnic_mrz_match.group(1)
            details['CNIC'] = f"{c[:5]}-{c[5:12]}-{c[12]}"

    # Parse MRZ Line 1 (Names)
    mrz1_pattern = r'P<PAK([A-Z<]+)'
    mrz1_match = re.search(mrz1_pattern, clean_text)
    if mrz1_match:
        name_str = mrz1_match.group(1).rstrip('<') # Remove trailing filler <<<
        
        if name_str.startswith('<<'):
            details['Surname'] = ""
            details['Given Name'] = name_str.strip('<').replace('<', ' ')
        elif '<<' in name_str:
            parts = name_str.split('<<', 1)
            details['Surname'] = parts[0].replace('<', ' ').strip()
            details['Given Name'] = parts[1].strip('<').replace('<', ' ').strip()
        else:
            details['Surname'] = name_str.strip('<').replace('<', ' ').strip()
            details['Given Name'] = ""
            
        details['Surname'] = clean_name_garbage(details['Surname'])
        details['Given Name'] = clean_name_garbage(details['Given Name'])

    # Fallback for Passport from top if MRZ failed
    if not details['Passport']:
        ppt_matches = re.findall(r'\b([A-Z]{2}[0-9]{7})\b', top_text.replace('O', '0'))
        if ppt_matches:
            details['Passport'] = ppt_matches[0]

    return details

# --- HELPER: AUTO-ENHANCE FACE PHOTO ---
def auto_enhance_face_photo(img):
    img = ImageEnhance.Color(img).enhance(1.1)
    img = ImageEnhance.Brightness(img).enhance(1.05)
    img = ImageEnhance.Contrast(img).enhance(1.1)
    img = ImageEnhance.Sharpness(img).enhance(1.5) 
    return img

# --- HELPER: PROCESS PHOTO SIZE & FORMAT (5-12KB) ---
def format_photo_for_requirements(uploaded_photo):
    img = Image.open(uploaded_photo)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
        
    img = auto_enhance_face_photo(img)
    img = img.resize((120, 150), Image.Resampling.LANCZOS)
    
    quality = 95
    output_bytes = io.BytesIO()
    
    while quality > 5:
        output_bytes.seek(0)
        output_bytes.truncate(0)
        img.save(output_bytes, format='JPEG', quality=quality)
        size_kb = output_bytes.tell() / 1024
        
        if 5 <= size_kb <= 12:
            break
        elif size_kb > 12:
            quality -= 5
        else:
            break # Agar pehle hi 5 se choti ho jaye tou nikal aao
            
    return output_bytes.getvalue()

# --- FOLDER BANANE KA LOGIC ---
SAVE_DIR = "Saved_Photos"
if not os.path.exists(SAVE_DIR): 
    os.makedirs(SAVE_DIR)

# --- UI SETTINGS ---
st.markdown("---")
setting_col1, setting_col2 = st.columns(2)
with setting_col1:
    airline_code = st.text_input("✈️ Airline Code (e.g. sv, pk, qr):", value="sv", max_chars=2)
with setting_col2:
    num_pax = st.number_input("👥 Total Passengers to Process:", min_value=1, max_value=10, value=1)

st.markdown("---")

# --- MULTIPLE PASSENGER UPLOAD ROWS ---
pax_data = []
for i in range(num_pax):
    st.markdown(f"#### 👤 Passenger {i+1}")
    c1, c2 = st.columns(2)
    with c1:
        ppt_file = st.file_uploader(f"Upload Passport for Pax {i+1}", type=['jpg', 'png', 'jpeg'], key=f"ppt_{i}")
    with c2:
        pic_file = st.file_uploader(f"Upload Photo for Pax {i+1}", type=['jpg', 'png', 'jpeg'], key=f"pic_{i}")
    
    pax_data.append({'passport': ppt_file, 'photo': pic_file, 'pax_no': i+1})
    st.markdown("---")

# --- PROCESS BUTTON ---
if st.button("💾 PROCESS ALL PASSENGERS", type="primary", use_container_width=True):
    if not OCR_AVAILABLE:
        st.error("⚠️ OCR Library Missing. Tesseract install hona zaroori hai.")
    else:
        # Check incomplete uploads
        incomplete = False
        for p in pax_data:
            if (p['passport'] and not p['photo']) or (not p['passport'] and p['photo']):
                incomplete = True
                st.warning(f"⚠️ Passenger {p['pax_no']} ka Passport ya Photo missing hai!")
                
        if incomplete:
            st.stop()
            
        # Process Valid Passengers
        with st.spinner("🔍 Tamam Passengers ka data scan ho raha hai..."):
            for p in pax_data:
                if p['passport'] and p['photo']:
                    try:
                        # 1. OCR Data Extraction
                        image = Image.open(p['passport'])
                        extracted = parse_passport_data_perfect(image)
                        
                        sur_name = extracted.get('Surname', '')
                        given_name = extracted.get('Given Name', '')
                        ppt_num = extracted.get('Passport', '')
                        dob = extracted.get('DOB', '')
                        expiry = extracted.get('Expiry', '')
                        gen = extracted['Gender']
                        cnic = extracted['CNIC']
                        father = extracted['Father Name']
                        
                        # Set Filename
                        if not given_name and not sur_name:
                            clean_name = f"Saved_Photo_Pax{p['pax_no']}"
                        else:
                            clean_name = f"{given_name} {sur_name}".strip()
                            clean_name = re.sub(r'\s+', ' ', clean_name)
                        
                        if not ppt_num: 
                            ppt_num = "NoPassport"
                            
                        file_name = f"{clean_name}_{ppt_num}.jpg".strip("_")
                        save_path = os.path.join(SAVE_DIR, file_name)
                        
                        # 2. Process & Enhance Photo
                        final_photo_bytes = format_photo_for_requirements(p['photo'])
                        file_size_kb = len(final_photo_bytes) / 1024
                        
                        with open(save_path, "wb") as f:
                            f.write(final_photo_bytes)
                            
                        # 3. Display Results
                        with st.expander(f"✅ Passenger {p['pax_no']}: {given_name} {sur_name}", expanded=True):
                            res1, res2 = st.columns([1, 2.5])
                            with res1:
                                st.image(final_photo_bytes, caption=f"Size: {file_size_kb:.1f} KB\nDim: 120x150 px", width=150)
                                st.download_button(
                                    label=f"⬇️ Download Photo",
                                    data=final_photo_bytes,
                                    file_name=file_name,
                                    mime="image/jpeg",
                                    key=f"dl_{p['pax_no']}"
                                )
                            with res2:
                                col_det1, col_det2 = st.columns(2)
                                
                                with col_det1:
                                    st.write(f"**Surname:** {sur_name if sur_name else '---'}")
                                    st.write(f"**Father/Husband:** {father if father else 'Not Found'}")
                                    st.write(f"**CNIC:** {cnic if cnic else 'Not Found'}")
                                    
                                with col_det2:
                                    st.write(f"**Given Name:** {given_name if given_name else '---'}")
                                    st.write(f"**Passport No:** {ppt_num}")
                                    st.write(f"**DOB:** {dob} | **Exp:** {expiry}")
                                    st.write(f"**Gender:** {gen}")
                                
                                st.markdown("---")
                                st.write("✈️ **Amadeus SR DOCS Command:**")
                                
                                surname_cmd = sur_name.replace(" ", "").lower()
                                givenname_cmd = given_name.replace(" ", "").lower()
                                
                                sr_docs_cmd = f"SRDOCS {airline_code.lower()} HK1-P-pak-{ppt_num.lower()}-pak-{dob.lower()}-{gen}-{expiry.lower()}-{surname_cmd}-{givenname_cmd}-h/p{p['pax_no']}"
                                
                                st.code(sr_docs_cmd, language="text")
                                
                    except Exception as e:
                        st.error(f"Error processing Passenger {p['pax_no']}: {e}")
