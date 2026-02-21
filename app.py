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
st.set_page_config(page_title="Auto Photo Saver", page_icon="📸", layout="centered")

st.title("📸 Auto Photo & Passport Saver")
st.markdown("Passport scan karein, system naam nikal kar photo ko enhance karega aur (5-12KB) mein save karega.")

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
    # Naam ke aakhir mein aane walay faltu K aur C ko hatayen (e.g. " K K KKKK")
    text = re.sub(r'(\s+[KC]+)+$', '', text)
    # Agar aakhri lafz ke sath ghalti se C jur gaya ho (jaise RAHIMC)
    if text.endswith('C') and len(text) > 3:
        text = text[:-1]
    return text.strip()

# --- HELPER: SMARTER PASSPORT EXTRACTOR ---
def parse_passport_mrz(text):
    details = {'Given Name': '', 'Surname': '', 'Passport': ''}
    
    clean_text = text.replace(" ", "").upper()
    for char in ['«', '¢', '(', '[', '{', '£', '€']:
        clean_text = clean_text.replace(char, "<")
    
    lines = clean_text.split('\n')
    mrz_line1 = ""
    mrz_line2 = ""
    
    for i, line in enumerate(lines):
        if "P<" in line and len(line) > 20:
            mrz_line1 = line[line.find("P<"):] 
            if i + 1 < len(lines):
                mrz_line2 = lines[i+1]
            break
            
    if mrz_line1:
        try:
            raw_name_data = mrz_line1[5:].strip('<')
            if '<<' in raw_name_data:
                name_parts = raw_name_data.split('<<', 1)
                surname = name_parts[0].replace('<', ' ').strip()
                given_name = name_parts[1].replace('<', ' ').strip()
                
                # Naye cleaner function se naam saaf karein
                details['Surname'] = clean_garbage(re.sub(r'[^A-Z ]', '', surname))
                details['Given Name'] = clean_garbage(re.sub(r'[^A-Z ]', '', given_name))
            else:
                parts = raw_name_data.split('<')
                valid_parts = []
                for p in parts:
                    cleaned_part = re.sub(r'[^A-Z]', '', p.strip())
                    if not cleaned_part: continue
                    # Agar OCR noise ka block aa jaye toh aage parhna chor dein
                    if re.match(r'^[KC]{2,}$', cleaned_part):
                        break
                    valid_parts.append(cleaned_part)
                
                if valid_parts:
                    details['Surname'] = clean_garbage(valid_parts[0])
                    if len(valid_parts) > 1:
                        details['Given Name'] = clean_garbage(" ".join(valid_parts[1:]))
        except Exception as e:
            pass

    if mrz_line2 and len(mrz_line2) >= 9:
        potential_ppt = re.sub(r'[^A-Z0-9]', '', mrz_line2[:9])
        if len(potential_ppt) >= 7:
            details['Passport'] = potential_ppt
            
    if not details['Passport']:
        matches = re.findall(r'\b[A-Z0-9]{8,10}\b', clean_text)
        for m in matches:
            if any(c.isdigit() for c in m) and "BEARY" not in m and "PAK" not in m:
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
                extracted = parse_passport_mrz(text)
                
                given_name = extracted.get('Given Name', '').strip()
                sur_name = extracted.get('Surname', '').strip()
                ppt_num = extracted.get('Passport', '').strip()
                
                if not given_name: given_name = "Unknown"
                if not sur_name: sur_name = "Name"
                if not ppt_num: ppt_num = "NoPassport"
                
                # 3. Clean Name for File
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
                
                # 4. Display Results with Copy Feature
                res1, res2 = st.columns([1, 2])
                with res1:
                    st.image(final_photo_bytes, caption=f"Size: {file_size_kb:.1f} KB\nDim: 120x150 px\n✨ Enhanced", width=150)
                with res2:
                    st.write("📋 **Extracted Details:**")
                    st.write(f"- **Given Name:** {given_name}") 
                    st.write(f"- **Surname:** {sur_name}")
                    st.write(f"- **Passport No:** {ppt_num}")
                    
                    st.markdown("---")
                    st.write("📝 **Copy Data for Amadeus:**")
                    
                    full_name_for_copy = f"{given_name} {sur_name}".strip()
                    st.code(full_name_for_copy, language="text")
                    st.code(f"{ppt_num}", language="text")
                    
                    st.markdown("---")
                    st.download_button(
                        label=f"⬇️ Download Enhanced Photo",
                        data=final_photo_bytes,
                        file_name=file_name,
                        mime="image/jpeg",
                        type="primary"
                    )
                    
            except Exception as e:
                st.error(f"Error: {e}")
