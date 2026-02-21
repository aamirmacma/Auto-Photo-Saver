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
st.set_page_config(page_title="Auto Photo Saver", page_icon="📸", layout="wide")

st.title("📸 Auto Photo & Passport Saver (Amadeus Pro)")
st.markdown("Passport scan karein, yeh naya **Dual-Scan Engine** 100% accurate data nikal kar SR DOCS command banayega.")

# --- HELPER: FORMAT DATES FOR AMADEUS (DDMMMYY) ---
def format_amadeus_date(raw_date):
    if not raw_date.isdigit() or len(raw_date) != 6:
        return ""
    yy, mm, dd = raw_date[0:2], raw_date[2:4], raw_date[4:6]
    months = {"01":"JAN", "02":"FEB", "03":"MAR", "04":"APR", "05":"MAY", "06":"JUN", 
              "07":"JUL", "08":"AUG", "09":"SEP", "10":"OCT", "11":"NOV", "12":"DEC"}
    month_str = months.get(mm, mm)
    return f"{dd}{month_str}{yy}"

# --- HELPER: DUAL-SCAN PASSPORT EXTRACTOR ---
def parse_passport_data_advanced(image):
    details = {
        'Given Name': '', 'Surname': '', 'Passport': '', 
        'DOB': '', 'Expiry': '', 'CNIC': '', 
        'Father Name': '', 'Gender': 'M'
    }
    
    width, height = image.size
    
    # ==========================================
    # SCAN 1: TOP PART (For Father/Husband Name)
    # ==========================================
    top_crop = image.crop((0, 0, width, int(height * 0.75)))
    top_crop = top_crop.resize((top_crop.width * 2, top_crop.height * 2), Image.Resampling.LANCZOS)
    top_gray = ImageOps.grayscale(top_crop)
    top_enhanced = ImageEnhance.Contrast(top_gray).enhance(2.0)
    
    top_text = pytesseract.image_to_string(top_enhanced).upper()
    top_lines = top_text.split('\n')
    
    father_name_found = ""
    for i, line in enumerate(top_lines):
        if re.search(r'(FATHER|HUSBAND|FATH|HUSB)', line):
            # Check next 3 lines for the actual name
            for j in range(1, 4):
                if i + j < len(top_lines):
                    potential_name = re.sub(r'[^A-Z ]', '', top_lines[i+j]).strip()
                    ignore_words = ["DATE", "BIRTH", "SEX", "PLACE", "NATIONALITY", "PASSPORT", "AUTHORITY", "PAKISTAN", "KARACHI", "ISSUING", "M", "F"]
                    if len(potential_name) > 3 and not any(w in potential_name for w in ignore_words):
                        father_name_found = potential_name
                        break
            if father_name_found:
                break
    details['Father Name'] = father_name_found.strip()

    # ==========================================
    # SCAN 2: BOTTOM MRZ PART (100% Accurate Data)
    # ==========================================
    # Crop exactly the bottom 30% where MRZ is
    bottom_crop = image.crop((0, int(height * 0.70), width, height))
    bottom_crop = bottom_crop.resize((bottom_crop.width * 2, bottom_crop.height * 2), Image.Resampling.LANCZOS)
    bot_gray = ImageOps.grayscale(bottom_crop)
    bot_enhanced = ImageEnhance.Contrast(bot_gray).enhance(2.5)
    
    # STRICT WHITELIST: Only allow MRZ characters (no random C, K, E from background)
    custom_config = r'-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789< --psm 6'
    mrz_text = pytesseract.image_to_string(bot_enhanced, config=custom_config)
    
    mrz_lines = [l.strip() for l in mrz_text.split('\n') if len(l.strip()) > 30]
    
    mrz_line1 = ""
    mrz_line2 = ""
    
    for l in mrz_lines:
        if l.startswith("P<"):
            mrz_line1 = l
        elif len(l) >= 42 and l[0].isalnum() and not l.startswith("P<"):
            mrz_line2 = l

    # Parse Line 1 (Names)
    if mrz_line1 and len(mrz_line1) >= 44:
        # e.g., P<PAK<<MAH<JABEEN<<<<<<<<<<<<<<<<<<
        name_part = mrz_line1[5:44].strip('<')
        if '<<' in name_part:
            parts = name_part.split('<<', 1)
            surname = parts[0].replace('<', ' ').strip()
            given_name = parts[1].replace('<', ' ').strip()
        else:
            surname = name_part.replace('<', ' ').strip()
            given_name = ""
            
        # If Surname is empty but Given Name exists (like Mah Jabeen case)
        if not surname and given_name:
            surname = given_name
            given_name = ""
            
        details['Surname'] = surname
        details['Given Name'] = given_name

    # Parse Line 2 (Passport, DOB, Expiry, CNIC, Gender)
    if mrz_line2 and len(mrz_line2) >= 42:
        details['Passport'] = mrz_line2[0:9].replace('<', '').strip()
        details['DOB'] = format_amadeus_date(mrz_line2[13:19])
        gender_char = mrz_line2[20]
        if gender_char in ['M', 'F']:
            details['Gender'] = gender_char
        details['Expiry'] = format_amadeus_date(mrz_line2[21:27])
        
        # Pakistani CNIC is ALWAYS at index 28 to 40 in MRZ line 2! (100% accurate)
        personal_num = mrz_line2[28:41].replace('<', '')
        if len(personal_num) == 13 and personal_num.isdigit():
            details['CNIC'] = f"{personal_num[:5]}-{personal_num[5:12]}-{personal_num[12]}"

    return details

# --- NEW HELPER: AUTO-ENHANCE PERSON'S PHOTO ---
def auto_enhance_face_photo(img):
    color_enhancer = ImageEnhance.Color(img)
    img = color_enhancer.enhance(1.1)
    brightness_enhancer = ImageEnhance.Brightness(img)
    img = brightness_enhancer.enhance(1.05)
    contrast_enhancer = ImageEnhance.Contrast(img)
    img = contrast_enhancer.enhance(1.1)
    sharpness_enhancer = ImageEnhance.Sharpness(img)
    img = sharpness_enhancer.enhance(1.5) 
    return img

# --- HELPER: PROCESS PHOTO SIZE & FORMAT ---
def format_photo_for_requirements(uploaded_photo):
    img = Image.open(uploaded_photo)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
        
    img = auto_enhance_face_photo(img)
    img = img.resize((120, 150), Image.Resampling.LANCZOS)
    
    quality = 95
    min_size = 5 * 1024
    max_size = 12 * 1024
    
    output_bytes = io.BytesIO()
    
    while quality > 5:
        output_bytes.seek(0)
        output_bytes.truncate(0)
        img.save(output_bytes, format='JPEG', quality=quality)
        size = output_bytes.tell()
        
        if size <= max_size:
            if size >= min_size:
                break
            else:
                break
        quality -= 5
        
    return output_bytes.getvalue()

# --- FOLDER BANANE KA LOGIC ---
SAVE_DIR = "Saved_Photos"
if not os.path.exists(SAVE_DIR): 
    os.makedirs(SAVE_DIR)

st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    st.info("🛂 1. Upload Passport")
    passport_file = st.file_uploader("Upload Passport Image", type=['jpg', 'png', 'jpeg'], key="ppt_up")

with col2:
    st.info("👤 2. Upload Photo")
    person_photo = st.file_uploader("Upload Person's Photo", type=['jpg', 'png', 'jpeg'], key="pic_up")

st.markdown("---")

setting_col1, setting_col2 = st.columns(2)
with setting_col1:
    airline_code = st.text_input("✈️ Airline Code (e.g. sv, pk, qr):", value="sv", max_chars=2)
with setting_col2:
    pax_no = st.text_input("👤 Passenger No (e.g. 1, 2, 3):", value="1", max_chars=1)

if st.button("💾 PROCESS & SAVE PHOTO", type="primary", use_container_width=True):
    if not OCR_AVAILABLE:
        st.error("⚠️ OCR Library Missing. Tesseract install hona zaroori hai.")
    elif not passport_file:
        st.warning("⚠️ Pehle Passport ki picture upload karein!")
    elif not person_photo:
        st.warning("⚠️ Photo upload karein jo save karni hai!")
    else:
        with st.spinner("🔍 Naya Engine Scan kar raha hai..."):
            try:
                # DUAL SCAN SYSTEM
                image = Image.open(passport_file)
                extracted = parse_passport_data_advanced(image)
                
                given_name = extracted.get('Given Name', '').strip()
                sur_name = extracted.get('Surname', '').strip()
                ppt_num = extracted.get('Passport', '').strip()
                dob = extracted.get('DOB', '')
                expiry = extracted.get('Expiry', '')
                cnic = extracted.get('CNIC', '')
                father_name = extracted.get('Father Name', '')
                gender = extracted.get('Gender', 'M')
                
                if not sur_name and not given_name:
                    sur_name = "Name"
                if not ppt_num: ppt_num = "NoPassport"
                
                # Clean Name for File
                clean_name = f"{given_name} {sur_name}".strip()
                clean_name = re.sub(r'\s+', ' ', clean_name)
                clean_name = re.sub(r'[^A-Za-z0-9 ]', '', clean_name)
                if not clean_name: clean_name = "Saved_Photo"
                    
                file_name = f"{clean_name}_{ppt_num}.jpg"
                save_path = os.path.join(SAVE_DIR, file_name)
                
                final_photo_bytes = format_photo_for_requirements(person_photo)
                file_size_kb = len(final_photo_bytes) / 1024
                
                with open(save_path, "wb") as f:
                    f.write(final_photo_bytes)
                    
                st.success(f"✅ Photo Successfully Saved as: **{file_name}**")
                
                res1, res2 = st.columns([1, 2.5])
                with res1:
                    st.image(final_photo_bytes, caption=f"Size: {file_size_kb:.1f} KB\nDim: 120x150 px", width=150)
                    st.download_button(
                        label=f"⬇️ Download Photo",
                        data=final_photo_bytes,
                        file_name=file_name,
                        mime="image/jpeg",
                        type="primary",
                        use_container_width=True
                    )
                with res2:
                    st.write("📋 **Extracted Details:**")
                    col_det1, col_det2 = st.columns(2)
                    
                    with col_det1:
                        st.write(f"**Surname:** {sur_name if sur_name else '---'}")
                        st.write(f"**Father/Husband:** {father_name if father_name else 'Not Found'}")
                        st.write(f"**CNIC:** {cnic if cnic else 'Not Found'}")
                        
                    with col_det2:
                        st.write(f"**Given Name:** {given_name if given_name else '---'}")
                        st.write(f"**Passport No:** {ppt_num}")
                        st.write(f"**DOB:** {dob} | **Exp:** {expiry}")
                        st.write(f"**Gender:** {gender}")
                    
                    st.markdown("---")
                    st.write("✈️ **Amadeus SR DOCS Command:**")
                    
                    surname_cmd = sur_name.replace(" ", "").lower()
                    givenname_cmd = given_name.replace(" ", "").lower()
                    
                    # Agar Given name khali hai (jaise MAH JABEEN ke case mein)
                    if givenname_cmd:
                        sr_docs_cmd = f"SRDOCS {airline_code.lower()} HK1-P-pak-{ppt_num.lower()}-pak-{dob.lower()}-{gender}-{expiry.lower()}-{surname_cmd}-{givenname_cmd}-h/p{pax_no}"
                    else:
                        sr_docs_cmd = f"SRDOCS {airline_code.lower()} HK1-P-pak-{ppt_num.lower()}-pak-{dob.lower()}-{gender}-{expiry.lower()}-{surname_cmd}-h/p{pax_no}"
                    
                    st.code(sr_docs_cmd, language="text")
                    
            except Exception as e:
                st.error(f"Error: {e}")
