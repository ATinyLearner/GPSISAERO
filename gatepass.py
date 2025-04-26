import streamlit as st
st.set_page_config(page_title="Gate Pass Application", layout="centered")
from PIL import Image
import io
import firebase_admin
from firebase_admin import credentials, firestore, storage
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import pytesseract
from pdf2image import convert_from_bytes

# ---------------------------------------------------

# Load Firebase credentials from Streamlit secrets and infer storage bucket
firebase_secrets = st.secrets.get("firebase", {})
if not firebase_secrets:
    st.error("⚠️ Missing 'firebase' section in st.secrets. Please add your Firebase credentials under [firebase].")
    st.stop()

# Normalize private key newlines
private_key = firebase_secrets.get("private_key", "").replace("\\n", "\n")

cred_dict = {
    "type": firebase_secrets.get("type"),
    "project_id": firebase_secrets.get("project_id"),
    "private_key_id": firebase_secrets.get("private_key_id"),
    "private_key": private_key,
    "client_email": firebase_secrets.get("client_email"),
    "client_id": firebase_secrets.get("client_id"),
    "auth_uri": firebase_secrets.get("auth_uri"),
    "token_uri": firebase_secrets.get("token_uri"),
    "auth_provider_x509_cert_url": firebase_secrets.get("auth_provider_x509_cert_url"),
    "client_x509_cert_url": firebase_secrets.get("client_x509_cert_url")
}

# Determine storage bucket: use explicit secret or default to <project_id>.appspot.com
project_id = firebase_secrets.get("project_id")
storage_bucket = firebase_secrets.get("storage_bucket") or f"{project_id}.appspot.com"

# Initialize Firebase with storageBucket
if not firebase_admin._apps:
    try:
        firebase_admin.initialize_app(
            credentials.Certificate(cred_dict),
            {"storageBucket": storage_bucket}
        )
    except Exception as e:
        st.error(f"Failed to initialize Firebase: {e}")
        st.stop()

# Firestore client
db = firestore.client()
# Storage bucket
bucket = storage.bucket()
# ---------------------------------------------------
st.title("Gate Pass for Drone Workshop")
st.subheader("Skill Stork International School in collaboration with Aerofoil Innovations Pvt Ltd")

# Applicant Details
name = st.text_input("Name")
reg_no = st.text_input("Registration Number")
phone = st.text_input("Phone Number")
email = st.text_input("Email ID")

# File upload and validation (100–500 KB enforced via code)
def validate_file(file, min_kb=100, max_kb=500):
    size_kb = len(file.read()) / 1024
    file.seek(0)
    if size_kb < min_kb or size_kb > max_kb:
        return False, f"File size must be between {min_kb} KB and {max_kb} KB. Uploaded: {int(size_kb)} KB"
    return True, None

# Checks that image corners are near-white
def check_white_bg(image):
    pixels = [
        image.getpixel((0, 0)),
        image.getpixel((image.width-1, 0)),
        image.getpixel((0, image.height-1)),
        image.getpixel((image.width-1, image.height-1))
    ]
    return all(sum(pixel)/3 > 240 for pixel in pixels)

# Uses OCR to verify clear text (for Aadhar clarity)
def ocr_check(file_bytes):
    try:
        images = convert_from_bytes(file_bytes)
        text = pytesseract.image_to_string(images[0])
    except Exception:
        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image)
    return len(text.strip()) > 50

# Uploaders: indicate the 500 KB limit in labels
passport_file = st.file_uploader("Passport Photo/PDF (white background, ≤500 KB)", type=["png","jpg","jpeg","pdf"])
aadhar_file = st.file_uploader("Aadhar Photo/PDF (clear text, ≤500 KB)", type=["png","jpg","jpeg","pdf"])

if st.button("Submit"):
    # Ensure all inputs are provided
    if not all([name, reg_no, phone, email, passport_file, aadhar_file]):
        st.error("Please fill all fields and upload both files.")
        st.stop()

    # Validate passport
    valid, msg = validate_file(passport_file)
    if not valid:
        st.error(f"Passport Error: {msg}")
        st.stop()
    passport_bytes = passport_file.read()
    passport_file.seek(0)
    try:
        img = Image.open(io.BytesIO(passport_bytes)).convert("RGB")
        if not check_white_bg(img):
            st.error("Passport photo background must be white.")
            st.stop()
    except Exception:
        pass

    # Validate Aadhar
    valid, msg = validate_file(aadhar_file)
    if not valid:
        st.error(f"Aadhar Error: {msg}")
        st.stop()
    aadhar_bytes = aadhar_file.read()
    aadhar_file.seek(0)
    if not ocr_check(aadhar_bytes):
        st.error("Aadhar details not clear. Please upload a clearer image.")
        st.stop()

    # Generate QR code
    qr_data = f"Name:{name}|RegNo:{reg_no}|Email:{email}|Phone:{phone}"
    qr_img = qrcode.make(qr_data)
    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    # Create Gate Pass PDF
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width/2, height-50, "Gate Pass for Drone Workshop")
    c.setFont("Helvetica", 12)
    c.drawCentredString(width/2, height-70, "Skill Stork International School in collaboration with Aerofoil Innovations Pvt Ltd")
    try:
        student_img = Image.open(io.BytesIO(passport_bytes)).convert("RGB")
        student_buffer = io.BytesIO()
        student_img.save(student_buffer, format="PNG")
        student_buffer.seek(0)
        c.drawImage(student_buffer, 50, height-250, width=100, height=100)
    except Exception:
        pass
    c.drawString(200, height-150, f"Name: {name}")
    c.drawString(200, height-170, f"Registration No: {reg_no}")
    c.drawString(200, height-190, f"Phone: {phone}")
    c.drawString(200, height-210, f"Email: {email}")
    c.drawImage(qr_buffer, 50, height-400, width=100, height=100)
    c.showPage()
    c.save()
    pdf_buffer.seek(0)

    # Upload files to Firebase Storage
    passport_blob = bucket.blob(f"gatepasses/{reg_no}/passport")
    passport_blob.upload_from_string(passport_bytes, content_type=passport_file.type)
    aadhar_blob = bucket.blob(f"gatepasses/{reg_no}/aadhar")
    aadhar_blob.upload_from_string(aadhar_bytes, content_type=aadhar_file.type)
    qr_blob = bucket.blob(f"gatepasses/{reg_no}/qr.png")
    qr_blob.upload_from_string(qr_buffer.getvalue(), content_type="image/png")
    pdf_blob = bucket.blob(f"gatepasses/{reg_no}/gatepass.pdf")
    pdf_blob.upload_from_string(pdf_buffer.getvalue(), content_type="application/pdf")

    # Save metadata to Firestore
    doc_ref = db.collection("gatepasses").document(reg_no)
    doc_ref.set({
        "name": name,
        "reg_no": reg_no,
        "email": email,
        "phone": phone,
        "qr_path": qr_blob.path,
        "pdf_path": pdf_blob.path,
        "timestamp": firestore.SERVER_TIMESTAMP
    })

    st.success("Gate pass generated and data saved successfully!")
    st.download_button("Download Gate Pass PDF", data=pdf_buffer, file_name=f"GatePass_{reg_no}.pdf", mime="application/pdf")