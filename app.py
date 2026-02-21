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
st.set_page_config(page_title="Auto Photo Saver (Pro Batch)", page_icon="📸", layout="wide")

st.title("📸 Auto Photo & Passport Saver (Pro Batch)")
st.markdown("Har passenger ka Passport aur Photo uske makhsoos box mein upload karein taake koi data mix na ho.")

# --- HELPER: CLEAN NAME GARBAGE ---
def clean_name_garbage(text):
    text = re.sub(r'[^A-Z ]', '', text.upper())
    # 3 ya us se zyada K, S, C, X, E agar end mein aayen tou unko kaat do
    text = re.sub(r'([KCSXE]\s*){3,}.*$', '', text)
    # Aakhir mein bacha hua akela stray letter (separated by space)
    text = re.sub(r'\s+[KCSXE]$', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- HELPER: MRZ DATE FORMATTER ---
def format_mrz_date(raw_date):
    if not raw_date.isdigit() or len(raw_date) != 6:
        return ""
    yy, mm, dd = raw_date[0:2], raw_date[2:4], raw_date[4:6]
    months = {"01":"JAN", "02":"FEB", "03":"MAR", "04":"APR", "05":"MAY", "06":"JUN", 
              "07":"JUL", "08":"AUG", "09":"SEP", "10":"OCT", "11":"NOV", "12":"DEC"}
    month_str = months.get(mm, mm)
    return f"{dd}{month_str}{yy}"

# --- HELPER: PERFECT PASSPORT EXTRACTOR ---
def parse_passport_data_perfect(image):
    details = {
        'Given Name': '', 'Surname': '', 'Passport': '', 
        'DOB': '', 'Expiry': '', 'CNIC': '', 
        'Father Name': '', 'Gender': 'M'
    }
    
    width, height = image.size
    
    # 1. TOP HALF SCAN (Father Name & CNIC)
    top_crop = image.crop((0, 0, width, int(height * 0.70)))
    top_enh = ImageEnhance.Contrast(ImageOps.grayscale(top_crop.resize((top_crop.width * 2, top_crop.height * 2)))).enhance(2.0)
    top_text = pytesseract.image_to_string(top_enh).upper()
    
    cnic_matches = re.findall(r'\b(\d{5}-\d{7}-\d)\b', top_text)
    if cnic_matches:
        details['CNIC'] = cnic_matches[0]
        
    lines = top_text.split('\n')
    for i, line in enumerate(lines):
        if re.search(r'(FATHER|HUSBAND|FATH|HUSB)', line):
            for j in range(1, 4):
                if i + j < len(lines):
                    cand = re.sub(r'[^A-Z ]', '', lines[i+j]).strip()
                    ignore = ["DATE", "BIRTH", "SEX", "PLACE", "NATIONALITY", "PASSPORT", "AUTHORITY", "PAKISTAN", "KARACHI", "ISSUING", "OF", "NAME", "REPUBLIC", "M", "F"]
                    if len(cand) > 3 and not any(w in cand for w in ignore):
                        details['Father Name'] = clean_name_garbage(cand)
                        break
            if details['Father Name']:
                break

    # 2. BOTTOM HALF SCAN (Strict MRZ Parsing with Binarization)
    bot_crop = image.crop((0, int(height * 0.60), width, height))
    bot_gray = ImageOps.grayscale(bot_crop.resize((bot_crop.width * 2, bot_crop.height * 2), Image.Resampling.LANCZOS))
    # Thresholding: Background watermarks ko completely white kar dega, sirf text black rahega
    bot_bw = bot_gray.point(lambda x: 0 if x < 130 else 255, '1')
    
    mrz_config = r'-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789< --psm 6'
    mrz_text = pytesseract.image_to_string(bot_bw, config=mrz_config).upper()
    
    clean_text = mrz_text.replace(" ", "") 
    
    # Passport, DOB, Gender, Expiry (Exact Pattern Match)
    mrz2_pattern = r'([A-Z0-9<]{8,9})[0-9<][A-Z<]{3}(\d{6})[0-9<]([MF<])(\d{6})'
    mrz2_match = re.search(mrz2_pattern, clean_text)
    
    if mrz2_match:
        details['Passport'] = mrz2_match.group(1).replace('<', '').replace('O', '0')
        details['DOB'] = format_mrz_date(mrz2_match.group(2))
        gender_char = mrz2_match.group(3)
        details['Gender'] = gender_char if gender_char in ['M', 'F'] else 'M'
        details['Expiry'] = format_mrz_date(mrz2_match.group(4))
        
    # Names (MRZ Line 1)
    mrz1_pattern = r'P<PAK([A-Z<]+)'
    mrz1_match = re.search(mrz1_pattern, clean_text)
    if mrz1_match:
        name_str = mrz1_match.group(1)
        name_str = re.sub(r'[KCSXZE<]+$', '', name_str) # Strip trailing garbage immediately
        
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

    # Fallback Passport
    if not details['Passport']:
        ppt_matches = re.findall(r'\b([A-Z]{2}[0-9]{7})\b', top_text.replace('O', '0'))
        if ppt_matches:
            details['Passport'] = ppt_matches[0]

    return details

# --- HELPER: AUTO-ENHANCE PERSON'S PHOTO ---
def auto_enhance_face_photo(img):
    img = ImageEnhance.Color(img).enhance(1.1)
    img = ImageEnhance.Brightness(img).enhance(1.05)
    img = ImageEnhance.Contrast(img).enhance(1.1)
    img = ImageEnhance.Sharpness(img).enhance(1.5) 
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

# --- UI SETTINGS ---
setting_col1, setting_col2 = st.columns(2)
with setting_col1:
    airline_code = st.text_input("✈️ Airline Code (e.g. sv, pk, qr):", value="sv", max_chars=2)
with setting_col2:
    num_pax = st.number_input("👥 Total Passengers to Process:", min_value=1, max_value=10, value=1)

st.markdown("---")

# --- DYNAMIC PASSENGER UPLOAD ROWS ---
pax_data = []
for i in range(num_pax):
    st.markdown(f"#### 👤 Passenger {i+1}")
    c1, c2 = st.columns(2)
    with c1:
        ppt = st.file_uploader(f"Passport for Pax {i+1}", type=['jpg', 'png', 'jpeg'], key=f"ppt_{i}")
    with c2:
        pic = st.file_uploader(f"Photo for Pax {i+1}", type=['jpg', 'png', 'jpeg'], key=f"pic_{i}")
    pax_data.append({'passport': ppt, 'photo': pic, 'pax_no': i+1})
    st.markdown("---")

# --- PROCESS BUTTON ---
if st.button("💾 PROCESS ALL PASSENGERS", type="primary", use_container_width=True):
    if not OCR_AVAILABLE:
        st.error("⚠️ OCR Library Missing. Tesseract install hona zaroori hai.")
    else:
        # Check if any data is missing
        missing_data = any(p['passport'] is None or p['photo'] is None for p in pax_data)
        if missing_data:
            st.warning("⚠️ Barae meharbani tamam passengers ke Passport aur Photo upload karein!")
        else:
            with st.spinner("🔍 Tamam Passengers ka data scan ho raha hai..."):
                for p in pax_data:
                    ppt_file = p['passport']
                    pic_file = p['photo']
                    current_pax_no = p['pax_no']
                    
                    try:
                        image = Image.open(ppt_file)
                        extracted = parse_passport_data_perfect(image)
                        
                        given_name = extracted.get('Given Name', '').strip()
                        sur_name = extracted.get('Surname', '').strip()
                        ppt_num = extracted.get('Passport', '').strip()
                        dob = extracted.get('DOB', '')
                        expiry = extracted.get('Expiry', '')
                        cnic = extracted.get('CNIC', '')
                        father_name = extracted.get('Father Name', '')
                        gender = extracted.get('Gender', 'M')
                        
                        if not given_name and not sur_name:
                            clean_name = f"Saved_Photo_{current_pax_no}"
                        else:
                            clean_name = f"{given_name} {sur_name}".strip()
                            clean_name = re.sub(r'\s+', ' ', clean_name)
                        
                        if not ppt_num: ppt_num = "NoPassport"
                            
                        file_name = f"{clean_name}_{ppt_num}.jpg"
                        save_path = os.path.join(SAVE_DIR, file_name)
                        
                        final_photo_bytes = format_photo_for_requirements(pic_file)
                        file_size_kb = len(final_photo_bytes) / 1024
                        
                        with open(save_path, "wb") as f:
                            f.write(final_photo_bytes)
                            
                        # Display Results
                        with st.expander(f"✅ PNR Details: Passenger {current_pax_no} - {given_name} {sur_name}", expanded=True):
                            res1, res2 = st.columns([1, 2.5])
                            with res1:
                                st.image(final_photo_bytes, caption=f"Size: {file_size_kb:.1f} KB\nDim: 120x150 px", width=150)
                                st.download_button(
                                    label=f"⬇️ Download Photo",
                                    data=final_photo_bytes,
                                    file_name=file_name,
                                    mime="image/jpeg",
                                    key=f"dl_{current_pax_no}"
                                )
                            with res2:
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
                                
                                sr_docs_cmd = f"SRDOCS {airline_code.lower()} HK1-P-pak-{ppt_num.lower()}-pak-{dob.lower()}-{gender}-{expiry.lower()}-{surname_cmd}-{givenname_cmd}-h/p{current_pax_no}"
                                
                                st.code(sr_docs_cmd, language="text")
                                
                    except Exception as e:
                        st.error(f"Error processing Passenger {current_pax_no}: {e}")
