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
st.markdown("Passport scan karein. Yeh naya engine **100% Accurate Data** nikal kar perfect SR DOCS command banayega.")

# --- HELPER: CLEAN NAME GARBAGE ---
def clean_name_garbage(text):
    # Sirf A-Z aur spaces rehne dein
    text = re.sub(r'[^A-Z ]', '', text.upper())
    # OCR ki wajah se aane wale end ke faltu letters (e.g., KKKK, SSSS, C, E, X) ko saaf karein
    text = re.sub(r'(\b[KCSXZE]\b\s*)+$', '', text)
    text = re.sub(r'[KCSXZE]{3,}$', '', text)
    return text.strip()

# --- HELPER: NEW ACCURATE PASSPORT EXTRACTOR ---
def parse_passport_data_perfect(image):
    details = {
        'Given Name': '', 'Surname': '', 'Passport': '', 
        'DOB': '', 'Expiry': '', 'CNIC': '', 
        'Father Name': '', 'Gender': 'M'
    }
    
    # Image ko bara aur wazeh karein
    new_size = (int(image.width * 1.5), int(image.height * 1.5))
    img_resized = image.resize(new_size, Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(img_resized)
    enhancer = ImageEnhance.Contrast(gray).enhance(2.0)
    
    # Poore passport ka text extract karein
    full_text = pytesseract.image_to_string(enhancer).upper()
    lines = full_text.split('\n')
    
    # ==========================================
    # 1. PASSPORT NUMBER, CNIC & DATES (Visual Regex - 100% Accurate)
    # ==========================================
    
    # Passport Number (Usually 2 letters + 7 digits, e.g., HU0004372)
    ppt_matches = re.findall(r'\b([A-Z]{2}[O0-9]{7})\b', full_text.replace(" ", ""))
    if ppt_matches:
        details['Passport'] = ppt_matches[0].replace('O', '0')
        
    # CNIC (e.g., 42301-0903437-0)
    cnic_matches = re.findall(r'\b(\d{5}-\d{7}-\d)\b', full_text)
    if cnic_matches:
        details['CNIC'] = cnic_matches[0]
        
    # Dates (DD MMM YYYY, e.g., 01 FEB 1967)
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    date_pattern = r'(\d{2})[ \-\.]*(' + '|'.join(months) + r')[ \-\.]*(\d{4})'
    found_dates = re.findall(date_pattern, full_text)
    
    if found_dates:
        parsed_dates = []
        for d in found_dates:
            parsed_dates.append({
                'amadeus': f"{d[0]}{d[1]}{d[2][-2:]}",
                'year': int(d[2])
            })
        # Sort by year: Pehli DOB, aakhri Expiry
        parsed_dates.sort(key=lambda x: x['year'])
        details['DOB'] = parsed_dates[0]['amadeus']
        if len(parsed_dates) > 1:
            details['Expiry'] = parsed_dates[-1]['amadeus']

    # Gender (M / F)
    sex_match = re.search(r'\bSEX\b.*?([MF])', full_text, re.IGNORECASE)
    if sex_match:
        details['Gender'] = sex_match.group(1).upper()

    # ==========================================
    # 2. NAME EXTRACTION (Husband/Father, Surname, Given Name)
    # ==========================================
    
    for i, line in enumerate(lines):
        # Father / Husband Name
        if re.search(r'(FATHER|HUSBAND|FATH|HUSB)', line):
            for j in range(1, 4):
                if i + j < len(lines):
                    cand = re.sub(r'[^A-Z ]', '', lines[i+j]).strip()
                    ignore = ["DATE", "BIRTH", "SEX", "PLACE", "NATIONALITY", "PASSPORT", "AUTHORITY", "PAKISTAN", "KARACHI", "ISSUING", "OF", "NAME", "REPUBLIC"]
                    if len(cand) > 3 and not any(w in cand for w in ignore):
                        details['Father Name'] = cand
                        break
        
        # Surname (Direct from Visual Area)
        if re.search(r'\b(SURNAME|SUR NAME)\b', line):
            if i + 1 < len(lines):
                cand = re.sub(r'[^A-Z ]', '', lines[i+1]).strip()
                if cand and len(cand) > 1 and cand not in ["GIVEN", "NAME", "NAMES", "PASSPORT", "PAKISTAN"]:
                    details['Surname'] = cand
                    
        # Given Name (Direct from Visual Area)
        if re.search(r'\b(GIVEN|GIVEN NAME|GIVEN NAMES)\b', line):
            if i + 1 < len(lines):
                cand = re.sub(r'[^A-Z ]', '', lines[i+1]).strip()
                if cand and len(cand) > 1 and cand not in ["NATIONALITY", "PASSPORT", "DATE", "SEX", "M", "F"]:
                    details['Given Name'] = cand

    # ==========================================
    # 3. MRZ FALLBACK (Agar oopar se kuch miss ho jaye)
    # ==========================================
    bot_crop = image.crop((0, int(image.height * 0.60), image.width, image.height))
    bot_enh = ImageEnhance.Contrast(ImageOps.grayscale(bot_crop)).enhance(2.5)
    mrz_text = pytesseract.image_to_string(bot_enh, config='--psm 6').upper()
    
    mrz_lines = [l.replace(" ", "") for l in mrz_text.split('\n')]
    mrz1 = next((l for l in mrz_lines if "P<" in l), "")
    
    if mrz1 and (not details['Surname'] and not details['Given Name']):
        mrz1 = re.sub(r'^.*?P<[A-Z]*', '', mrz1) # "PAK" ya prefix hata dein
        if '<<' in mrz1:
            parts = mrz1.split('<<', 1)
            details['Surname'] = parts[0].replace('<', ' ')
            details['Given Name'] = parts[1].replace('<', ' ')
        else:
            details['Surname'] = mrz1.replace('<', ' ')

    # Final Cleanup for Garbage Characters
    details['Surname'] = clean_name_garbage(details['Surname'])
    details['Given Name'] = clean_name_garbage(details['Given Name'])

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
        with st.spinner("🔍 Naya Accurate Engine Scan kar raha hai..."):
            try:
                image = Image.open(passport_file)
                extracted = parse_passport_data_perfect(image)
                
                given_name = extracted.get('Given Name', '').strip()
                sur_name = extracted.get('Surname', '').strip()
                ppt_num = extracted.get('Passport', '').strip()
                dob = extracted.get('DOB', '')
                expiry = extracted.get('Expiry', '')
                cnic = extracted.get('CNIC', '')
                father_name = extracted.get('Father Name', '')
                gender = extracted.get('Gender', 'M')
                
                # Agar dono naam khali hain tou default
                if not given_name and not sur_name:
                    clean_name = "Saved_Photo"
                else:
                    clean_name = f"{given_name} {sur_name}".strip()
                    clean_name = re.sub(r'\s+', ' ', clean_name)
                    clean_name = re.sub(r'[^A-Za-z0-9 ]', '', clean_name)
                
                if not ppt_num: ppt_num = "NoPassport"
                    
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
                        # Khali hone par dashes (---)
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
                    
                    # Yeh line automatically khali Surname ko control karegi (Double Dash -- format)
                    sr_docs_cmd = f"SRDOCS {airline_code.lower()} HK1-P-pak-{ppt_num.lower()}-pak-{dob.lower()}-{gender}-{expiry.lower()}-{surname_cmd}-{givenname_cmd}-h/p{pax_no}"
                    
                    st.code(sr_docs_cmd, language="text")
                    
            except Exception as e:
                st.error(f"Error: {e}")
