import streamlit as st
from PIL import Image
import io
import os
import firebase_admin
from firebase_admin import credentials, firestore, storage
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import pytesseract
from pdf2image import convert_from_bytes

# Initialize Firebase
FIREBASE_CRED_PATH = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'path/to/serviceAccountKey.json')
FIREBASE_STORAGE_BUCKET = 'your-bucket-name.appspot.com'

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CRED_PATH)
    firebase_admin.initialize_app(cred, {
        'storageBucket': FIREBASE_STORAGE_BUCKET
    })

db = firestore.client()
bucket = storage.bucket()

st.set_page_config(page_title='Gate Pass Application', layout='centered')
st.title('Gate Pass for Drone Workshop')
st.subheader('Skill Stork International School in collaboration with Aerofoil Innovations Pvt Ltd')

# Applicant Details
name = st.text_input('Name')
reg_no = st.text_input('Registration Number')
phone = st.text_input('Phone Number')
email = st.text_input('Email ID')

# File upload and validation functions
def validate_file(file, min_kb=100, max_kb=500):
    size_kb = len(file.read()) / 1024
    file.seek(0)
    if size_kb < min_kb or size_kb > max_kb:
        return False, f'File size must be between {min_kb} KB and {max_kb} KB. Uploaded: {int(size_kb)} KB'
    return True, None


def check_white_bg(image):
    # Simple check: sample corners
    pixels = [image.getpixel((0,0)), image.getpixel((image.width-1,0)),
              image.getpixel((0,image.height-1)), image.getpixel((image.width-1,image.height-1))]
    # Check if all sampled pixels are near white
    return all(sum(pixel)/3 > 240 for pixel in pixels)


def ocr_check(file_bytes):
    # OCR on first page if PDF, else direct
    try:
        # PDF
        images = convert_from_bytes(file_bytes)
        text = pytesseract.image_to_string(images[0])
    except:
        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image)
    return len(text.strip()) > 50

# Uploaders
passport_file = st.file_uploader('Upload Passport Photo or PDF (white background)', type=['png','jpg','jpeg','pdf'])
aadhar_file = st.file_uploader('Upload Aadhar Card Photo or PDF', type=['png','jpg','jpeg','pdf'])

if st.button('Submit'):
    if not all([name, reg_no, phone, email, passport_file, aadhar_file]):
        st.error('Please fill all fields and upload both files.')
    else:
        # Validate passport
        valid, msg = validate_file(passport_file)
        if not valid:
            st.error(f'Passport Error: {msg}')
            st.stop()
        passport_bytes = passport_file.read()
        passport_file.seek(0)
        # White background check
        try:
            img = Image.open(io.BytesIO(passport_bytes)).convert('RGB')
            if not check_white_bg(img):
                st.error('Passport photo background must be white.')
                st.stop()
        except:
            pass  # skip for PDF

        # Validate aadhar
        valid, msg = validate_file(aadhar_file)
        if not valid:
            st.error(f'Aadhar Error: {msg}')
            st.stop()
        aadhar_bytes = aadhar_file.read()
        aadhar_file.seek(0)
        if not ocr_check(aadhar_bytes):
            st.error('Aadhar details not clear. Please upload a clearer image.')
            st.stop()

        # Generate QR code
        qr_data = f"Name:{name}|RegNo:{reg_no}|Email:{email}|Phone:{phone}"
        qr_img = qrcode.make(qr_data)
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)

        # Create Gate Pass PDF
        pdf_buffer = io.BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=A4)
        width, height = A4
        c.setFont('Helvetica-Bold', 18)
        c.drawCentredString(width/2, height-50, 'Gate Pass for Drone Workshop')
        c.setFont('Helvetica', 12)
        c.drawCentredString(width/2, height-70, 'Skill Stork International School in collaboration with Aerofoil Innovations Pvt Ltd')
        # Draw student image
        try:
            student_img = Image.open(io.BytesIO(passport_bytes)).convert('RGB')
            student_buffer = io.BytesIO()
            student_img.save(student_buffer, format='PNG')
            student_buffer.seek(0)
            c.drawImage(student_buffer, 50, height-250, width=100, height=100)
        except:
            pass
        # Text details
        c.drawString(200, height-150, f'Name: {name}')
        c.drawString(200, height-170, f'Registration No: {reg_no}')
        # Draw QR
        c.drawImage(qr_buffer, 50, height-350, width=100, height=100)
        c.showPage()
        c.save()
        pdf_buffer.seek(0)

        # Store files in Firebase
        # Passport
        passport_blob = bucket.blob(f'gatepasses/{reg_no}/passport')
        passport_blob.upload_from_string(passport_bytes, content_type=passport_file.type)
        # Aadhar
        aadhar_blob = bucket.blob(f'gatepasses/{reg_no}/aadhar')
        aadhar_blob.upload_from_string(aadhar_bytes, content_type=aadhar_file.type)
        # QR
        qr_blob = bucket.blob(f'gatepasses/{reg_no}/qr.png')
        qr_blob.upload_from_string(qr_buffer.getvalue(), content_type='image/png')
        # PDF
        pdf_blob = bucket.blob(f'gatepasses/{reg_no}/gatepass.pdf')
        pdf_blob.upload_from_string(pdf_buffer.getvalue(), content_type='application/pdf')

        # Firestore entry
        doc_ref = db.collection('gatepasses').document(reg_no)
        doc_ref.set({
            'name': name,
            'reg_no': reg_no,
            'email': email,
            'phone': phone,
            'qr_path': qr_blob.path,
            'pdf_path': pdf_blob.path,
            'timestamp': firestore.SERVER_TIMESTAMP
        })

        st.success('Gate pass generated and data saved successfully!')
        st.download_button('Download Gate Pass PDF', data=pdf_buffer, file_name=f'GatePass_{reg_no}.pdf', mime='application/pdf')
