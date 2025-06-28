#!/usr/bin/env python3
"""
Complete Medicine Parser OCR Solution
Single file containing all functionality for parsing medicines from OCR text.

Usage:
    from medicine_parser_complete import parse_medicines_image
    
    ocr_text = "Your OCR text here..."
    meds = parse_medicines_image(ocr_text)
    
    for med in meds:
        print(f"Medicine: {med['Medicine']}, Dosage: {med['Dosage']}, Duration: {med['Duration']}")
"""

import re
import logging
from difflib import SequenceMatcher

# Configure logging
logging.basicConfig(level=logging.INFO)

# Known medicines database for fuzzy matching
KNOWN_MEDICINES = [
    # Common pain relievers
    "Paracetamol", "Acetaminophen", "Ibuprofen", "Aspirin", "Diclofenac", "Naproxen",
    
    # Antibiotics
    "Amoxicillin", "Azithromycin", "Ciprofloxacin", "Doxycycline", "Erythromycin",
    "Metronidazole", "Clindamycin", "Cephalexin", "Ampicillin", "Penicillin",
    
    # Antacids and digestive
    "Omeprazole", "Pantoprazole", "Ranitidine", "Famotidine", "Domperidone",
    "Metoclopramide", "Ondansetron", "Simethicone", "Sucralfate",
    
    # Cardiovascular
    "Atenolol", "Metoprolol", "Amlodipine", "Losartan", "Enalapril", "Furosemide",
    "Atorvastatin", "Simvastatin", "Clopidogrel", "Warfarin",
    
    # Diabetes
    "Metformin", "Glibenclamide", "Gliclazide", "Glimepiride", "Insulin", "Pioglitazone",
    
    # Respiratory
    "Salbutamol", "Prednisolone", "Dexamethasone", "Montelukast", "Cetirizine",
    "Loratadine", "Phenylephrine", "Guaifenesin",
    
    # Mental health
    "Sertraline", "Fluoxetine", "Alprazolam", "Lorazepam", "Diazepam",
    
    # Vitamins and supplements
    "Vitamin D", "Vitamin B12", "Folic Acid", "Iron", "Calcium", "Zinc",
    
    # Topical medications
    "Betamethasone", "Hydrocortisone", "Clotrimazole", "Ketoconazole",
    
    # Neurological medications
    "Sumatriptan", "Topiramate", "Levetiracetam", "Valproate", "Amitriptyline",
    "Tramadol", "Codeine", "Morphine", "Gabapentin", "Pregabalin",
    
    # Tuberculosis medications
    "Rifampicin", "Isoniazid",
    
    # COVID-19 medications
    "Favipiravir",
    
    # Heart medications
    "Carvedilol", "Rosuvastatin",
    
    # Allergy medications (additional)
    "Montair",
    
    # UTI medications
    "Nitrofurantoin",
    
    # Contraceptives and hormonal
    "Diane",
    
    # Gout medications
    "Allopurinol", "Colchicine",
    
    # Bone health
    "Calcitriol", "Ferrous", "Sulphate",
    
    # Weight management
    "Orlistat", "Phentermine",
    
    # Others
    "Levothyroxine", "Thyronorm", "Alendronate", "Acyclovir", "Fluconazole"
]

def fuzzy_match(text, medicine_list, threshold=0.75):
    """
    Find medicines in text using fuzzy string matching with stricter criteria
    """
    found_medicines = []
    text_lower = text.lower()
    
    for medicine in medicine_list:
        medicine_lower = medicine.lower()
        
        # Direct substring match (exact)
        if medicine_lower in text_lower:
            found_medicines.append(medicine)
            continue
            
        # Check for partial matches - require at least 6 characters for partial match
        if len(medicine_lower) >= 6:
            # Look for significant portions of the medicine name
            min_match_length = max(5, int(len(medicine_lower) * 0.7))
            for i in range(len(medicine_lower) - min_match_length + 1):
                substring = medicine_lower[i:i+min_match_length]
                if substring in text_lower:
                    found_medicines.append(medicine)
                    break
            else:
                # Fuzzy matching for OCR errors - stricter threshold
                words = text_lower.split()
                for word in words:
                    if len(word) >= 5:  # Only match words 5+ characters
                        # Check if word is similar enough to medicine name
                        similarity = SequenceMatcher(None, medicine_lower, word).ratio()
                        if similarity >= threshold:
                            found_medicines.append(medicine)
                            break
        else:
            # For shorter medicine names, require higher similarity
            words = text_lower.split()
            for word in words:
                if len(word) >= len(medicine_lower) - 1:  # Allow 1 character difference
                    similarity = SequenceMatcher(None, medicine_lower, word).ratio()
                    if similarity >= 0.85:  # Higher threshold for short names
                        found_medicines.append(medicine)
                        break
    
    # Remove duplicates while preserving order
    return list(dict.fromkeys(found_medicines))

def parse_medicines_image(text):
    """
    Parse medicines from OCR text
    
    Args:
        text (str): OCR text containing prescription information
        
    Returns:
        list: List of dictionaries with medicine information
    """
    # Initial OCR fixes
    text = text.replace("Date;", "Date:")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    capture = False
    med_block = []

    # Extract medicine block - look for "No Medicine" marker
    for line in lines:
        if re.search(r'No\s*Medicine', line, re.IGNORECASE):
            capture = True
            if any(med.lower() in line.lower() for med in KNOWN_MEDICINES) or len(line.split()) > 3:
                med_block.append(line)
            continue
        if capture:
            if re.search(r'(Advice:|Signature|Dr\.|Next Visit)', line, re.IGNORECASE):
                break
            med_block.append(line)

    # OCR error correction function
    def fix_ocr_errors(line):
        line = re.sub(r"(?i)(\d)[oO]mg", r"\1mg", line)
        line = re.sub(r"(?i)(\d)[oO]mcg", r"\1mcg", line)
        line = re.sub(r"(?i)s00mg", "500mg", line)
        line = re.sub(r"(?i)Zmg", "2mg", line)
        line = re.sub(r"(?i)paracetam0l", "paracetamol", line)
        line = re.sub(r"(?i)ibupr0fen", "ibuprofen", line)
        line = re.sub(r"(?i)am0xicillin", "amoxicillin", line)
        line = re.sub(r"(?i)metf0rmin", "metformin", line)
        line = re.sub(r"(?i)0meprazole", "omeprazole", line)
        line = re.sub(r"(?i)salbutam0", "salbutamol", line)
        line = re.sub(r"(?i)m0ntelukast", "montelukast", line)
        return line

    # Apply OCR corrections
    med_block = [fix_ocr_errors(line) for line in med_block]
    block_text = " ".join(med_block)

    # Find medicines
    found_medicines = fuzzy_match(block_text, KNOWN_MEDICINES)

    # Fallback: search entire text if no medicines found
    if not found_medicines:
        full_text_fixed = fix_ocr_errors(text)
        found_medicines = fuzzy_match(full_text_fixed, KNOWN_MEDICINES)

    # Extract dosages and durations
    dosages = []
    durations = []
    
    # Search for dosages
    for line in med_block:
        line_dosages = re.findall(r"\b[0-9]{1,2}-[0-9]{1,2}-[0-9]{1,2}\b", line)
        dosages.extend(line_dosages)
    
    if not dosages:
        dosages = re.findall(r"\b[0-9]{1,2}-[0-9]{1,2}-[0-9]{1,2}\b", text)
    
    dosages = list(dict.fromkeys(dosages))
    
    # Search for durations
    for line in med_block:
        line_durations = re.findall(r"\b\d+\s*(?:day|days|week|weeks|month|months)\b", line, re.IGNORECASE)
        durations.extend(line_durations)
    
    if not durations:
        durations = re.findall(r"\b\d+\s*(?:day|days|week|weeks|month|months)\b", text, re.IGNORECASE)
    
    durations = list(dict.fromkeys(durations))

    # Normalize durations
    durations = [re.sub(r'\b(\d+)\s*day\b', r'\1 days', d, flags=re.IGNORECASE) for d in durations]
    durations = [re.sub(r'\b(\d+)\s*week\b', r'\1 weeks', d, flags=re.IGNORECASE) for d in durations]
    durations = [re.sub(r'\b(\d+)\s*month\b', r'\1 months', d, flags=re.IGNORECASE) for d in durations]

    count = len(found_medicines)
    if not count:
        return []

    # Align dosages and durations
    if len(dosages) > count * 2:
        dosages = dosages[:count]
    if len(durations) > count * 2:
        durations = durations[:count]

    if len(dosages) == 1 and count > 1:
        dosages *= count
    elif len(dosages) > count:
        dosages = dosages[:count]
    elif len(dosages) == 0:
        dosages = ["1-0-0"] * count
    elif len(dosages) < count:
        last_dosage = dosages[-1] if dosages else "1-0-0"
        while len(dosages) < count:
            dosages.append(last_dosage)
    
    if len(durations) == 1 and count > 1:
        durations *= count
    elif len(durations) > count:
        durations = durations[:count]
    elif len(durations) == 0:
        durations = ["3 days"] * count
    elif len(durations) < count:
        last_duration = durations[-1] if durations else "3 days"
        while len(durations) < count:
            durations.append(last_duration)

    # Build medicine list
    meds = []
    for i in range(count):
        meds.append({
            "No": str(i + 1),
            "Medicine": found_medicines[i].title(),
            "Dosage": dosages[i] if i < len(dosages) else "1-0-0",
            "Duration": durations[i] if i < len(durations) else "3 days",
            "Timing": ""
        })

    return meds

