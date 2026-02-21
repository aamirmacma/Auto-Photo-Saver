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
st.markdown("Har passenger ka Passport aur Photo uske makhsoos box mein upload karein taake koi data mix na ho.")

# --- HELPER: CLEAN NAME GARBAGE ---
def clean_name_garbage(text):
    text = re.sub(r'[^A-Z ]', '', text.upper())
    # 3 ya us se zyada K, S, C, X, E agar end mein aayen tou unko kaat do
    text = re.sub(r'([KCSXE]\s*){3,}.*$', '', text)
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
    bot_bw = bot_gray.point(lambda x: 0 if x < 130 else 255, '1')
    
    mrz_config = r'-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789< --psm 6'
    mrz_text = pytesseract.image_to_string(bot_bw, config=mrz_config).upper()
    
    clean_text = mrz_text.replace(" ", "") 
    
    mrz2_pattern = r'([A-Z0-9<]{8,9})[0-9<][A-Z<]{3}(\d{6})[0-9<]([MF<])(\d{6})'
    mrz2_match = re.search(mrz2_pattern, clean_text)
    
    if mrz2_match:
        details['Passport'] = mrz2_match.group(1).replace('<', '').replace('O', '0')
        details['DOB'] = format_mrz_date(mrz2_match.group(2))
        gender_char = mrz2_match.group(3)
        details['Gender'] = gender_char if gender_char in ['M', 'F'] else 'M'
        details['Expiry'] = format_mrz_date(mrz2_match.group(4))
        
    mrz1_pattern = r'P<PAK([A-Z<]+)'
    mrz1_match = re.search(mrz1_pattern, clean_text)
    if mrz1_match:
        name_str = mrz1_match.group(1)
        name_str = re.sub(r'[KCSXZE<]+$', '', name_str) 
        
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

    return details

# --- HELPER: AUTO-ENHANCE PHOTO ---
def auto_enhance_face_photo(img):
    img = ImageEnhance.Color(img).enhance(1.1)
    img = ImageEnhance.Brightness(img).enhance(1.05)
    img = ImageEnhance.Contrast(img).enhance(1.1)
    img = ImageEnhance.Sharpness(img).enhance(1.5) 
    return img

# --- HELPER: PROCESS PHOTO SIZE ---
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
        if 5 * 1024 <= output_bytes.tell() <= 12 * 1024:
            break
        quality -= 5
    return output_bytes.getvalue()

# --- FOLDER BANANE KA LOGIC ---
SAVE_DIR = "Saved_Photos"
if not os.path.exists(SAVE_DIR): 
    os.makedirs(SAVE_DIR)

# --- UI SETTINGS ---
st.markdown("---")
setting_col1, setting_col2 = st.columns(2)
with setting_col1:
    airline_code = st.text_input("✈️ Airline Code (sv, pk, qr):", value="sv", max_chars=2)
with setting_col2:
    num_pax = st.number_input("👥 Total Passengers to Process:", min_value=1, max_value=10, value=1)

st.markdown("---")

# --- MULTIPLE PASSENGER UPLOAD ROWS ---
pax_data = []
for i in range(num_pax):
    st.markdown(f"#### 👤 Passenger {i+1}")
    c1, c2 = st.columns(2)
    with c1:
        ppt = st.file_uploader(f"Upload Passport {i+1}", type=['jpg', 'png', 'jpeg'], key=f"ppt_{i}")
    with c2:
        pic = st.file_uploader(f"Upload Photo {i+1}", type=['jpg', 'png', 'jpeg'], key=f"pic_{i}")
    pax_data.append({'passport': ppt, 'photo': pic, 'pax_no': i+1})
    st.markdown("---")

# --- PROCESS BUTTON ---
if st.button("💾 PROCESS ALL PASSENGERS", type="primary", use_container_width=True):
    if not OCR_AVAILABLE:
        st.error("⚠️ OCR Library Missing.")
    else:
        # Check if any passenger data is missing
        if any(p['passport'] is None or p['photo'] is None for p in pax_data):
            st.warning("⚠️ Sab passengers ke Passport aur Photo upload karein!")
        else:
            with st.spinner("🔍 Scanning all passengers..."):
                for p in pax_data:
                    try:
                        image = Image.open(p['passport'])
                        extracted = parse_passport_data_perfect(image)
                        
                        # Extract Details
                        sur = extracted['Surname']
                        giv = extracted['Given Name']
                        ppt = extracted['Passport']
                        dob = extracted['DOB']
                        exp = extracted['Expiry']
                        gen = extracted['Gender']
                        cnic = extracted['CNIC']
                        father = extracted['Father Name']
                        
                        # Save Photo
                        photo_bytes = format_photo_for_requirements(p['photo'])
                        file_name = f"{giv}_{sur}_{ppt}.jpg".strip("_")
                        with open(os.path.join(SAVE_DIR, file_name), "wb") as f:
                            f.write(photo_bytes)
                        
                        # Display
                        with st.expander(f"✅ Passenger {p['pax_no']}: {giv} {sur}", expanded=True):
                            res1, res2 = st.columns([1, 2.5])
                            with res1:
                                st.image(photo_bytes, width=150)
                                st.download_button("Download Photo", data=photo_bytes, file_name=file_name, key=f"dl_{p['pax_no']}")
                            with res2:
                                col_a, col_b = st.columns(2)
                                with col_a:
                                    st.write(f"**Surname:** {sur if sur else '---'}")
                                    st.write(f"**Father:** {father}")
                                    st.write(f"**CNIC:** {cnic}")
                                with col_b:
                                    st.write(f"**Given Name:** {giv if giv else '---'}")
                                    st.write(f"**Passport:** {ppt}")
                                    st.write(f"**DOB:** {dob} | **Exp:** {exp}")
                                    st.write(f"**Gender:** {gen}")
                                
                                st.markdown("---")
                                sr_docs_cmd = f"SRDOCS {airline_code.lower()} HK1-P-pak-{ppt.lower()}-pak-{dob.lower()}-{gen}-{exp.lower()}-{sur.lower()}-{giv.lower()}-h/p{p['pax_no']}"
                                st.code(sr_docs_cmd, language="text")
                    except Exception as e:
                        st.error(f"Error in Passenger {p['pax_no']}: {e}")
