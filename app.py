#!/usr/bin/env python3
"""
Quiet Flask Application for Medicine Adherence System
Minimal logging output for cleaner command line experience
"""

import os
import re
import logging
import traceback
from flask import Flask, render_template, request, redirect, url_for, flash, session
import pandas as pd
from datetime import datetime, timedelta
import pytesseract
from PIL import Image
from pdf2image import convert_from_path
import easyocr
from werkzeug.utils import secure_filename
from PyPDF2 import PdfReader
import tempfile
import io
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from medicine_parser_complete import parse_medicines_image

# QUIET CONFIG - Minimal logging
APP_CONFIG = {
    "UPLOAD_FOLDER": "uploads",
    "ALLOWED_EXTENSIONS": {"pdf", "png", "jpg", "jpeg"},
    "MAX_CONTENT_LENGTH": 16 * 1024 * 1024,
    "LOG_FILE": "app.log",
    "MAX_IMAGE_DIM": 1200,
    "MIN_TEXT_LENGTH": 20,
    "OCR_TIMEOUT": 20,
    "TESSERACT_PATH": "/usr/bin/tesseract",
    "EASYOCR_LANGUAGES": ['en'],
    "SECRET_KEY": os.urandom(24)
}

# BLOB CONFIG
BLOB_CONFIG = {
    "CONNECTION_STRING": None,
    "ACCOUNT_URL": "https://mymedsmate.blob.core.windows.net",
    "SAS_TOKEN": "?sp=racwde&st=2025-06-13T08:16:14Z&se=2025-07-31T16:16:14Z&spr=https&sv=2024-11-04&sr=c&sig=1zjNij1YFZ8JC2V6rtuxWRAfju4UvAmO3b2f9S8IRmw%3D",
    "CONTAINER_NAME": "landing",
    "CSV_FILENAME": "presc_dtl_v1.csv"
}
app = Flask(__name__)
app.secret_key = APP_CONFIG['SECRET_KEY']
app.config.update(APP_CONFIG)
app.config.update({"BLOB_CONFIG": BLOB_CONFIG})

# QUIET LOGGING SETUP - Only show errors and critical messages
logging.basicConfig(
    level=logging.ERROR,  # Only show ERROR and CRITICAL
    format='%(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(app.config['LOG_FILE']),
        logging.StreamHandler()  # This controls console output
    ]
)

# Suppress Azure SDK logging completely
logging.getLogger('azure').setLevel(logging.CRITICAL)
logging.getLogger('azure.core.pipeline.policies.http_logging_policy').setLevel(logging.CRITICAL)
logging.getLogger('azure.storage.blob').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)

# Suppress other verbose loggers
logging.getLogger('PIL').setLevel(logging.CRITICAL)
logging.getLogger('pytesseract').setLevel(logging.CRITICAL)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize OCR engines quietly
try:
    pytesseract.pytesseract.tesseract_cmd = app.config['TESSERACT_PATH']
    reader = easyocr.Reader(app.config['EASYOCR_LANGUAGES'], gpu=False, verbose=False)
    print("✓ OCR engines ready")
except Exception as e:
    print(f"✗ OCR initialization failed: {e}")
    reader = None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def preprocess_image(input_path):
    """Optimize image for better OCR results"""
    try:
        with Image.open(input_path) as img:
            ratio = min(app.config['MAX_IMAGE_DIM'] / img.width, app.config['MAX_IMAGE_DIM'] / img.height, 1.0)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            resample = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS
            img = img.resize(new_size, resample)
            img = img.convert('L')
            
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                img.save(temp_file.name)
                return temp_file.name
    except Exception:
        return None

def secure_save(file):
    """Safely save uploaded file"""
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            file.save(save_path)
            return save_path
        except Exception:
            return None
    return None

def extract_text_easyocr(img_path):
    """Extract text using EasyOCR"""
    try:
        if reader is None:
            return ""
        return "\n".join(reader.readtext(img_path, detail=0, paragraph=True))
    except Exception:
        return ""

def extract_text_tesseract(img, config='--psm 6'):
    """Extract text using Tesseract"""
    try:
        return pytesseract.image_to_string(img, config=f'--oem 3 {config}')
    except Exception:
        return ""

def perform_ocr(img_path):
    """Perform OCR with fallback mechanism"""
    text = extract_text_easyocr(img_path)
    if len(text.strip()) >= app.config["MIN_TEXT_LENGTH"]:
        return text, "easyocr"
    
    try:
        with Image.open(img_path) as img:
            text = extract_text_tesseract(img)
        if len(text.strip()) >= app.config["MIN_TEXT_LENGTH"]:
            return text, "tesseract"
    except Exception:
        pass
    
    return "", None

def process_image(file_path):
    """Process image file for OCR"""
    processed_path = preprocess_image(file_path)
    try:
        if processed_path:
            text, method = perform_ocr(processed_path)
            return text
        return ""
    finally:
        if processed_path and os.path.exists(processed_path):
            os.remove(processed_path)

def process_pdf(file_path):
    """Process PDF file - extract text or convert to image for OCR"""
    try:
        reader = PdfReader(file_path)
        text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
        
        if text.strip():
            return text
        
        images = convert_from_path(file_path, dpi=200)
        if images:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                images[0].save(temp_file.name)
                return process_image(temp_file.name)
        
        return ""
    except Exception:
        return ""

def normalize_text(text):
    """Normalize OCR text for better processing"""
    text = text.replace('_', '.').replace(',', '.')
    return text

def extract_patient_info(text):
    """Extract patient information from OCR text - ROBUST VERSION with special format handling"""
    info = {
        "Patient Name": "Unknown",
        "Sex": "",
        "Phone": "",
        "Patient ID": "",
        "Birthdate": "",
        "Age": "",
        "Diagnosis": "",
        "Doctor Name": "",
        "Doctor ID": ""
    }

    # Clean text for better matching
    text_clean = re.sub(r'\s+', ' ', text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Handle special format: "Patient Name: Sex: Phone: Birthdate:" followed by "Name Gender Phone Date"
    for i, line in enumerate(lines):
        if "Patient Name:" in line and "Sex:" in line and "Phone:" in line and "Birthdate:" in line:
            # Found header line, check next line for data
            if i + 1 < len(lines):
                data_line = lines[i + 1].strip()
                parts = data_line.split()
                if len(parts) >= 4:
                    # Find phone number (10+ digits)
                    for j, part in enumerate(parts):
                        if re.match(r'^\d{10}', part):
                            info["Phone"] = part
                            # Gender is usually right before phone
                            if j > 0 and parts[j - 1] in ["Male", "Female"]:
                                info["Sex"] = parts[j - 1]
                                # Name is everything before gender
                                name_parts = parts[:j - 1]
                                if len(name_parts) >= 2:
                                    info["Patient Name"] = " ".join(name_parts)
                            # Birthdate typically after phone
                            if j + 1 < len(parts):
                                next_part = parts[j + 1]
                                if re.match(r'\d{2}-[A-Za-z]{3}-\d{4}', next_part):
                                    info["Birthdate"] = next_part
                            break
                break

    # Standard patterns for remaining fields
    patterns = {
        "Patient Name": [
            r"Patient Name:\s*([A-Za-z\s\.]+?)(?:\s+Age:|\s*$)",
            r"Patient Name:\s*([A-Za-z\s\.]+?)(?:\s+Age|\s*$)",
            r"Patient Name:([A-Za-z\s\.]+?)Age:",
            r"Patient Name:([A-Za-z\s\.]+?)(?:\s+Age|\s*$)"
        ],
        "Age": [
            r"Age:\s*(\d{1,3})",
            r"Age:(\d{1,3})",
            r"Age\s*:\s*(\d{1,3})"
        ],
        "Sex": [
            r"Sex:\s*(Male|Female)",
            r"Sex:(Male|Female)",
            r"Sex\s*:\s*(Male|Female)"
        ],
        "Phone": [
            r"Phone:\s*(\d{10,})",
            r"Phone:(\d{10,})",
            r"Phone\s*:\s*(\d{10,})"
        ],
        "Patient ID": [
            r"Patient ID:\s*(PID-[A-Za-z0-9\-]+)",
            r"Patient ID:(PID-[A-Za-z0-9\-]+)",
            r"Patient ID\s*:\s*(PID-[A-Za-z0-9\-]+)"
        ],
        "Birthdate": [
            r"Birthdate:\s*(\d{2}-[A-Za-z]{3}-\d{4})",
            r"Birthdate:(\d{2}-[A-Za-z]{3}-\d{4})"
        ]
    }

    # Apply standard patterns only if not already found
    for field, pattern_list in patterns.items():
        if info[field] == "" or (field == "Patient Name" and info[field] == "Unknown"):
            for pattern in pattern_list:
                match = re.search(pattern, text_clean, re.IGNORECASE)
                if match:
                    value = match.group(1).strip()
                    if field == "Patient Name" and len(value.split()) >= 2:
                        info[field] = value
                        break
                    elif field != "Patient Name" and value:
                        info[field] = value
                        break

    # Extract Diagnosis (handles PDF and OCR text)
    diag_patterns = [
        r"Diagnosis\s*:\s*(.*?)(?:No\s+Medicine|Dosage|Duration|$)",  # up to next label or end
        r"Diagnosis\s*-\s*(.*?)(?:No\s+Medicine|Dosage|Duration|$)",
        r"Diagnosis\s*:\s*(.+)",  # fallback: just after Diagnosis:
    ]
    for pattern in diag_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            diagnosis = match.group(1).strip(" :-\n\t")
            diagnosis = re.split(r'(No\s+Medicine|Dosage|Duration)', diagnosis)[0].strip()
            if diagnosis:
                info["Diagnosis"] = diagnosis
                break

    # Extract Doctor Name and Doctor ID
    docid_match = re.search(r"Doctor ID\s*[:\-]?\s*(DOC-\d{3})", text, re.IGNORECASE)
    if docid_match:
        info["Doctor ID"] = docid_match.group(1).strip()
    dr_matches = re.findall(r"(Dr\.\s*[A-Z][A-Za-z]+\s+[A-Z][A-Za-z]+)", text)
    if dr_matches:
        info["Doctor Name"] = dr_matches[-1].strip()

    # Calculate age from birthdate if age not found
    if not info["Age"] and info["Birthdate"]:
        try:
            dob = datetime.strptime(info["Birthdate"], "%d-%b-%Y")
            calculated_age = (datetime.now().date() - dob.date()).days // 365
            info["Age"] = str(calculated_age)
        except:
            pass

    return info

def get_end_date(start_date, duration):
    """Calculate end date based on duration"""
    try:
        match = re.match(r"(\d+)\s*(day|week|month|days|weeks|months)", duration.lower())
        if not match:
            return ""
        
        num = int(match.group(1))
        unit = match.group(2)
        
        if 'week' in unit:
            days = num * 7
        elif 'month' in unit:
            days = num * 30
        else:
            days = num
        
        end_date = start_date + timedelta(days=days - 1)
        return end_date.strftime("%Y-%m-%d")
    except Exception:
        return ""

def expand_frequency_rows(patient_info, medicines):
    """Expand medicines based on frequency to create one row per timing"""
    expanded_rows = []
    
    frequency_map = {
        "1-0-0": ["Morning"],
        "0-1-0": ["Afternoon"], 
        "0-0-1": ["Night"],
        "1-1-0": ["Morning", "Afternoon"],
        "1-0-1": ["Morning", "Night"],
        "0-1-1": ["Afternoon", "Night"],
        "1-1-1": ["Morning", "Afternoon", "Night"],
        "2-0-0": ["Morning", "Morning"],
        "0-2-0": ["Afternoon", "Afternoon"],
        "0-0-2": ["Night", "Night"],
        "2-1-1": ["Morning", "Morning", "Afternoon", "Night"],
        "1-2-1": ["Morning", "Afternoon", "Afternoon", "Night"],
        "1-1-2": ["Morning", "Afternoon", "Night", "Night"]
    }
    
    notification_times = {
        "Morning": "08:00",
        "Afternoon": "12:00", 
        "Evening": "18:00",
        "Night": "19:00"
    }
    
    now = datetime.now()
    
    for medicine in medicines:
        dosage = medicine.get('Dosage', '1-0-1')
        duration = medicine.get('Duration', '5 days')
        medicine_name = medicine.get('Medicine', 'Unknown')
        
        timings = frequency_map.get(dosage, ["Morning"])
        end_date = get_end_date(now.date(), duration)
        
        for timing in timings:
            row = {
                "Patient ID": patient_info.get("Patient ID", ""),
                "Patient Name": patient_info.get("Patient Name", "Unknown"),
                "Sex": patient_info.get("Sex", ""),
                "Phone": patient_info.get("Phone", ""),
                "Age": patient_info.get("Age", ""),
                "Diagnosis": patient_info.get("Diagnosis", ""),
                "Doctor Name": patient_info.get("Doctor Name", ""),
                "Doctor ID": patient_info.get("Doctor ID", ""),
                "Processed Time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "Start Date": now.strftime("%Y-%m-%d"),
                "End Date": end_date,
                "Medicine Name": medicine_name,
                "Frequency": timing,
                "Duration": duration,
                "Timing": timing,
                "Notification Time": notification_times.get(timing, "08:00"),
                "Medicine Img": f"{medicine_name}.png",
                "Alternate": "No",
                "Daily": "Yes"
            }
            expanded_rows.append(row)
    
    return expanded_rows

def save_prescription_to_blob(meds, text, config):
    try:
        info = extract_patient_info(text)
        now = datetime.now()

        # Expand medicines into full rows for CSV
        rows = expand_frequency_rows(info, meds)

        if not rows:
            logging.warning("No medicines found to save to blob.")
            return 0

        df = pd.DataFrame(rows)

        blob_service = BlobServiceClient(account_url=config['ACCOUNT_URL'], credential=config['SAS_TOKEN'])
        container_client = blob_service.get_container_client(config['CONTAINER_NAME'])
        blob_client = container_client.get_blob_client(config['CSV_FILENAME'])
        
        existing_df = pd.DataFrame()
        try:
            content = blob_client.download_blob().readall().decode('utf-8', errors='ignore')
            if content.strip():
                existing_df = pd.read_csv(io.StringIO(content))
        except ResourceNotFoundError:
            logging.info(f"Blob {config['CSV_FILENAME']} not found. A new one will be created.")
        except Exception as e:
            logging.error(f"Error reading existing CSV from blob: {e}\n{traceback.format_exc()}")

        combined_df = pd.concat([existing_df, df], ignore_index=True)
        blob_client.upload_blob(combined_df.to_csv(index=False).encode('utf-8'), overwrite=True)

        logging.info("Prescription data saved to Azure Blob Storage successfully.")
        return len(rows)
    except Exception as e:
        logging.exception(f"Error saving to blob: {e}")
        return 0

def check_auth():
    """Check if user is authenticated"""
    username = 'admin'
    return session.get('user') == username

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = 'admin'
        password = 'admin'
        
        if request.form['username'] == username and request.form['password'] == password:
            session['user'] = username
            return redirect(url_for('upload'))
        else:
            flash('Invalid credentials', 'error')
    
    return render_template('login.html', year=datetime.now().year)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if not check_auth():
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        files = request.files.getlist('file')
        success_count = 0
        total_records = 0
        
        if not files or all(not f.filename for f in files):
            flash("No file selected for upload.", "warning")
            return redirect(url_for('upload'))
        
        for f in files:
            if not f or not allowed_file(f.filename):
                flash(f"Invalid file type: {f.filename}", "error")
                continue
            
            path = secure_save(f)
            if not path:
                flash(f"Failed to save file: {f.filename}", "error")
                continue
            
            try:
                if not f.filename.lower().endswith(".pdf"):
                    with Image.open(path) as img:
                        img.verify()
                
                if f.filename.lower().endswith('.pdf'):
                    text = normalize_text(process_pdf(path))
                else:
                    text = normalize_text(process_image(path))
                
                if os.path.exists(path):
                    os.remove(path)
                
                if not text.strip():
                    flash(f"OCR failed or no text found in: {f.filename}", "error")
                    continue
                
                meds = parse_medicines_image(text)
                
                if not meds:
                    flash(f"No medicine details detected in: {f.filename}", "warning")
                    continue
                
                saved_count = save_prescription_to_blob(meds, text, app.config['BLOB_CONFIG'])
                
                if saved_count:
                    print(f"✓ {f.filename}: {len(meds)} medicines → {saved_count} records")
                    flash(f"Processed: {f.filename} ({len(meds)} medicines, {saved_count} records)", "success")
                    success_count += 1
                    total_records += saved_count
                else:
                    print(f"✗ {f.filename}: Failed to save")
                    flash(f"Failed to save data for: {f.filename}", "error")
                
            except Exception as e:
                print(f"✗ {f.filename}: Error - {str(e)}")
                flash(f"Error processing {f.filename}: {str(e)}", "error")
                
                if os.path.exists(path):
                    os.remove(path)
        
        if success_count > 0:
            print(f"\n✓ COMPLETED: {success_count} files processed, {total_records} total records\n")
            return render_template('upload_success.html', 
                                 year=datetime.now().year,
                                 processed_count=success_count,
                                 total_records=total_records)
        else:
            return redirect(url_for('upload'))
    
    return render_template('upload.html', year=datetime.now().year)

@app.route('/view_cloud_data', methods=['POST'])
def view_cloud_data():
    url = f"{app.config['BLOB_CONFIG']['ACCOUNT_URL'].rstrip('/')}/{app.config['BLOB_CONFIG']['CONTAINER_NAME']}/{app.config['BLOB_CONFIG']['CSV_FILENAME']}{app.config['BLOB_CONFIG']['SAS_TOKEN']}"
    return render_template('view_cloud_data.html', blob_url=url, year=datetime.now().year)



if __name__ == '__main__':
    
    print("🚀 Starting Medicine Adherence System...")
    #app.run(host='0.0.0.0', port=5000, debug=False)  # debug=False for quieter output