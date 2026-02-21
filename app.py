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
st.markdown("Passport scan karein, system CNIC, Father Name nikalega aur **Amadeus SR DOCS** command auto-generate karega.")

# --- HELPER: PASSPORT OCR PREPROCESSING ---
def preprocess_image_for_ocr(image):
    new_size = (int(image.width * 1.5), int(image.height * 1.5))
    img = image.resize(new_size, Image.Resampling.LANCZOS)
    
    gray_image = ImageOps.grayscale(img)
    enhancer = ImageEnhance.Contrast(gray_image)
    high_contrast = enhancer.enhance(2.0) 
    return high_contrast

# --- HELPER: CLEAN GARBAGE OCR NOISE ---
def clean_garbage(text):
    text = re.sub(r'(\s+[KC]+)+$', '', text)
    if text.endswith('C') and len(text) > 3:
        text = text[:-1]
    return text.strip()

# --- HELPER: FORMAT DATES FOR AMADEUS (DDMMMYY) ---
def format_amadeus_date(raw_date):
    if not raw_date.isdigit() or len(raw_date) != 6:
        return ""
    yy, mm, dd = raw_date[0:2], raw_date[2:4], raw_date[4:6]
    months = {"01":"JAN", "02":"FEB", "03":"MAR", "04":"APR", "05":"MAY", "06":"JUN", 
              "07":"JUL", "08":"AUG", "09":"SEP", "10":"OCT", "11":"NOV", "12":"DEC"}
    month_str = months.get(mm, mm)
    return f"{dd}{month_str}{yy}"

# --- HELPER: FULL PASSPORT EXTRACTOR ---
def parse_passport_data(text):
    details = {
        'Given Name': '', 'Surname': '', 'Passport': '', 
        'DOB': '', 'Expiry': '', 'CNIC': '', 
        'Father Name': '', 'Gender': 'M', 'Nationality': 'PAK'
    }
    
    # --- 1. Extract CNIC & Father/Husband Name from Original Text ---
    original_lines = text.upper().split('\n')
    
    # Find CNIC (Pattern: 12345-1234567-1 or without dashes)
    cnic_match = re.search(r'\b(\d{5})[-\s]?(\d{7})[-\s]?(\d)\b', text.upper())
    if cnic_match:
        details['CNIC'] = f"{cnic_match.group(1)}-{cnic_match.group(2)}-{cnic_match.group(3)}"
        
    # Find Father or Husband Name
    for i, line in enumerate(original_lines):
        if "FATHER" in line or "HUSBAND" in line:
            # Check the next 1 or 2 lines for the actual name
            for j in range(1, 3):
                if i + j < len(original_lines):
                    potential_name = re.sub(r'[^A-Z ]', '', original_lines[i+j]).strip()
                    # Filter out other labels that might be caught
                    if len(potential_name) > 3 and not any(x in potential_name for x in ["DATE", "SEX", "PLACE"]):
                        details['Father Name'] = clean_garbage(potential_name)
                        break
            break

    # --- 2. Extract Data from MRZ ---
    clean_text = text.replace(" ", "").upper()
    for char in ['«', '¢', '(', '[', '{', '£', '€']:
        clean_text = clean_text.replace(char, "<")
    
    mrz_lines = clean_text.split('\n')
    mrz_line1 = ""
    mrz_line2 = ""
    
    for i, line in enumerate(mrz_lines):
        if "P<" in line and len(line) > 20:
            mrz_line1 = line[line.find("P<"):] 
            if i + 1 < len(mrz_lines):
                mrz_line2 = mrz_lines[i+1]
            break
            
    # Name from Line 1
    if mrz_line1:
        try:
            details['Nationality'] = mrz_line1[2:5].replace('<', 'PAK') # Default PAK
            raw_name_data = mrz_line1[5:].strip('<')
            if '<<' in raw_name_data:
                name_parts = raw_name_data.split('<<', 1)
                surname = name_parts[0].replace('<', ' ').strip()
                given_name = name_parts[1].replace('<', ' ').strip()
                details['Surname'] = clean_garbage(re.sub(r'[^A-Z ]', '', surname))
                details['Given Name'] = clean_garbage(re.sub(r'[^A-Z ]', '', given_name))
        except:
            pass

    # PPT, DOB, Expiry, Gender from Line 2
    if mrz_line2 and len(mrz_line2) >= 28:
        potential_ppt = re.sub(r'[^A-Z0-9]', '', mrz_line2[:9])
        if len(potential_ppt) >= 7:
            details['Passport'] = potential_ppt
            
        details['DOB'] = format_amadeus_date(mrz_line2[13:19])
        details['Expiry'] = format_amadeus_date(mrz_line2[21:27])
        
        gender_char = mrz_line2[20]
        if gender_char in ['M', 'F']:
            details['Gender'] = gender_char

    # Fallback Passport
    if not details['Passport']:
        matches = re.findall(r'\b[A-Z0-9]{8,10}\b', clean_text)
        for m in matches:
            if any(c.isdigit() for c in m) and "PAK" not in m:
                details['Passport'] = m
                break
                
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

if st.button("💾 PROCESS & SAVE PHOTO", type="primary", use_container_width=True):
    if not OCR_AVAILABLE:
        st.error("⚠️ OCR Library Missing. Tesseract install hona zaroori hai.")
    elif not passport_file:
        st.warning("⚠️ Pehle Passport ki picture upload karein!")
    elif not person_photo:
        st.warning("⚠️ Photo upload karein jo save karni hai!")
    else:
        with st.spinner("🔍 Scan aur Process ho raha hai..."):
            try:
                # 1. OCR Data Extraction
                image = Image.open(passport_file)
                processed_image = preprocess_image_for_ocr(image)
                
                text = pytesseract.image_to_string(processed_image, config='--psm 6')
                extracted = parse_passport_data(text)
                
                given_name = extracted.get('Given Name', '').strip()
                sur_name = extracted.get('Surname', '').strip()
                ppt_num = extracted.get('Passport', '').strip()
                dob = extracted.get('DOB', 'Unknown')
                expiry = extracted.get('Expiry', 'Unknown')
                cnic = extracted.get('CNIC', 'Not Found')
                father_name = extracted.get('Father Name', 'Not Found')
                gender = extracted.get('Gender', 'M')
                nat = extracted.get('Nationality', 'PAK')
                
                if not given_name: given_name = "Unknown"
                if not sur_name: sur_name = "Name"
                if not ppt_num: ppt_num = "NoPassport"
                
                # Clean Name for File
                clean_name = f"{given_name} {sur_name}".replace("Unknown", "").strip()
                clean_name = re.sub(r'\s+', ' ', clean_name)
                clean_name = re.sub(r'[^A-Za-z0-9 ]', '', clean_name)
                
                if not clean_name: clean_name = "Saved_Photo"
                    
                file_name = f"{clean_name}_{ppt_num}.jpg"
                save_path = os.path.join(SAVE_DIR, file_name)
                
                # 2. Process & ENHANCE Photo
                final_photo_bytes = format_photo_for_requirements(person_photo)
                file_size_kb = len(final_photo_bytes) / 1024
                
                # 3. Save Photo
                with open(save_path, "wb") as f:
                    f.write(final_photo_bytes)
                    
                st.success(f"✅ Photo Successfully Saved as: **{file_name}**")
                
                # 4. Display Results with Full Amadeus Command
                res1, res2 = st.columns([1, 2.5])
                with res1:
                    st.image(final_photo_bytes, caption=f"Size: {file_size_kb:.1f} KB\nDim: 120x150 px\n✨ Enhanced", width=150)
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
                        st.write(f"**Name:** {given_name} {sur_name}")
                        st.write(f"**Father/Husband:** {father_name}")
                        st.write(f"**CNIC:** {cnic}")
                    with col_det2:
                        st.write(f"**Passport No:** {ppt_num}")
                        st.write(f"**DOB:** {dob} | **Exp:** {expiry}")
                        st.write(f"**Gender:** {gender}")
                    
                    st.markdown("---")
                    st.write("✈️ **Amadeus SR DOCS Command (Click to Copy):**")
                    
                    # Generate SR DOCS Format
                    # Format: SR DOCS YY HK1-P-PAK-{PPT}-PAK-{DOB}-{GENDER}-{EXPIRY}-{SURNAME}-{GIVENNAME}
                    sr_docs_cmd = f"SR DOCS YY HK1-P-{nat}-{ppt_num}-{nat}-{dob}-{gender}-{expiry}-{sur_name}-{given_name}"
                    
                    st.code(sr_docs_cmd, language="text")
                    st.caption("*Note: Aap 'YY' ki jagah apni specific airline ka code (e.g., PK, SV, QR) likh sakte hain.*")
                    
            except Exception as e:
                st.error(f"Error: {e}")
