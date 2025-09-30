import os
import csv
import json
import base64
from io import BytesIO
from datetime import datetime

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
import qrcode
from PIL import Image
from sqlalchemy.orm import Session

from .db import get_engine_from_env, create_session_factory, Base, Worker as DBWorker, Doctor as DBDoctor, Appointment as DBAppointment, Feedback as DBFeedback, seed_demo_data

# Load environment variables
load_dotenv()

# Environment configuration with defaults
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '5003'))
DEBUG = os.getenv('DEBUG', 'true').lower() == 'true'
CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*')
STORAGE_DIR = os.getenv('STORAGE_DIR', 'storage')
CSV_FILE = os.getenv('CSV_FILE', os.path.join(STORAGE_DIR, 'workers.csv'))
FACE_IMAGE_DIR = os.getenv('FACE_IMAGE_DIR', os.path.join(STORAGE_DIR, 'faces'))
QR_IMAGE_DIR = os.getenv('QR_IMAGE_DIR', os.path.join(STORAGE_DIR, 'qrs'))
SECRET_KEY = os.getenv('SECRET_KEY', 'change-this-secret')

# Ensure storage directories exist
os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(FACE_IMAGE_DIR, exist_ok=True)
os.makedirs(QR_IMAGE_DIR, exist_ok=True)

# Ensure CSV exists with header
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([
            'health_id', 'full_name', 'age', 'gender', 'phone', 'address', 'native_state',
            'blood_group', 'marital_status', 'language', 'financial_status',
            'allergies', 'conditions', 'inherited_diseases', 'previous_treatments', 'vaccination_count',
            'registration_date', 'face_filename', 'qr_filename'
        ])

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app, resources={r"/*": {"origins": CORS_ORIGINS}})

# Database init
engine = get_engine_from_env()
Base.metadata.create_all(bind=engine)
SessionFactory = create_session_factory(engine)
seed_demo_data(SessionFactory)


def _save_face_image(health_id: str, face_b64_data: str) -> str:
    """Save base64 image to FACE_IMAGE_DIR and return filename."""
    try:
        # Accept data URLs like "data:image/png;base64,xxxx"
        if ',' in face_b64_data:
            face_b64_data = face_b64_data.split(',')[1]
        image_bytes = base64.b64decode(face_b64_data)
        filename = f"{health_id}.png"
        path = os.path.join(FACE_IMAGE_DIR, filename)
        with open(path, 'wb') as f:
            f.write(image_bytes)
        return filename
    except Exception:
        return ''


def _generate_qr_image(content: str, health_id: str, face_filename: str | None) -> str:
    """Generate a QR code from content, optionally overlay a face thumbnail, save PNG, return filename."""
    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(content)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color='black', back_color='white').convert('RGB')

    # Try to overlay a small face thumbnail at bottom-right
    if face_filename:
        face_path = os.path.join(FACE_IMAGE_DIR, face_filename)
        if os.path.exists(face_path):
            try:
                face_img = Image.open(face_path).convert('RGB')
                # Create a square thumbnail
                thumb_size = max(64, qr_img.size[0] // 6)
                face_img.thumbnail((thumb_size, thumb_size))

                # Paste with a white border background for contrast
                bordered = Image.new('RGB', (face_img.width + 8, face_img.height + 8), 'white')
                bordered.paste(face_img, (4, 4))

                pos = (qr_img.size[0] - bordered.size[0] - 8, qr_img.size[1] - bordered.size[1] - 8)
                qr_img.paste(bordered, pos)
            except Exception:
                pass

    filename = f"{health_id}.png"
    out_path = os.path.join(QR_IMAGE_DIR, filename)
    qr_img.save(out_path, format='PNG')
    return filename


def _read_worker(health_id: str):
    session: Session = SessionFactory()
    try:
        w = session.query(DBWorker).filter_by(health_id=health_id).first()
        if not w:
            return None
        return {
            'health_id': w.health_id,
            'full_name': w.full_name,
            'age': str(w.age or ''),
            'gender': w.gender or '',
            'phone': w.phone or '',
            'address': w.address or '',
            'native_state': w.native_state or '',
            'blood_group': w.blood_group or '',
            'marital_status': w.marital_status or '',
            'language': w.language or '',
            'financial_status': w.financial_status or '',
            'allergies': w.allergies or '',
            'conditions': w.conditions or '',
            'inherited_diseases': w.inherited_diseases or '',
            'previous_treatments': w.previous_treatments or '',
            'vaccination_count': str(w.vaccination_count or 0),
            'registration_date': (w.registration_date.strftime('%Y-%m-%d') if w.registration_date else ''),
            'face_filename': w.face_filename or '',
            'qr_filename': w.qr_filename or '',
        }
    finally:
        session.close()


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200


@app.route('/api/workers', methods=['POST'])
def create_worker():
    """
    Accepts JSON with registration data. Expected fields:
      - healthId (required)
      - fullName, age, gender, phone, nativeState, language
      - faceImage (optional, base64 data URL or raw base64)
    Generates and stores face image and QR image; persists metadata in CSV.
    Returns JSON with worker data and URLs.
    """
    try:
        data = request.get_json(silent=True) or {}
        health_id = (data.get('healthId') or '').strip()
        if not health_id:
            return jsonify({'error': 'healthId is required'}), 400

        full_name = (data.get('fullName') or '').strip()
        age = int(data.get('age') or 0) or ''
        gender = (data.get('gender') or '').strip()
        phone = (data.get('phone') or '').strip()
        address = (data.get('address') or '').strip()
        native_state = (data.get('nativeState') or '').strip()
        blood_group = (data.get('bloodGroup') or '').strip()
        marital_status = (data.get('maritalStatus') or '').strip()
        language = (data.get('language') or '').strip()
        financial_status = (data.get('financialStatus') or '').strip()
        allergies = (data.get('allergies') or '').strip()
        conditions = (data.get('conditions') or '').strip()
        inherited_diseases = (data.get('inheritedDiseases') or '').strip()
        previous_treatments = (data.get('previousTreatments') or '').strip()
        vaccination_count = int(data.get('vaccinationCount') or 0)
        registration_date = data.get('registrationDate') or datetime.utcnow().strftime('%Y-%m-%d')
        face_b64 = data.get('faceImage')

        # Save face image
        face_filename = _save_face_image(health_id, face_b64) if face_b64 else ''

        # QR content: JSON payload
        qr_payload = {
            'healthId': health_id,
            'fullName': full_name,
            'gender': gender,
            'nativeState': native_state,
            'registrationDate': registration_date,
        }
        qr_text = json.dumps(qr_payload, ensure_ascii=False)
        qr_filename = _generate_qr_image(qr_text, health_id, face_filename or None)

        # Persist to DB (upsert by health_id)
        session: Session = SessionFactory()
        try:
            w = session.query(DBWorker).filter_by(health_id=health_id).first()
            if not w:
                w = DBWorker(health_id=health_id)
                session.add(w)
            w.full_name = full_name
            w.age = age or None
            w.gender = gender
            w.phone = phone
            w.address = address
            w.native_state = native_state
            w.blood_group = blood_group
            w.marital_status = marital_status
            w.language = language
            w.financial_status = financial_status
            w.allergies = allergies
            w.conditions = conditions
            w.inherited_diseases = inherited_diseases
            w.previous_treatments = previous_treatments
            w.vaccination_count = vaccination_count
            w.registration_date = datetime.strptime(registration_date, '%Y-%m-%d') if isinstance(registration_date, str) else registration_date
            w.face_filename = face_filename
            w.qr_filename = qr_filename
            session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()

        base_url = request.host_url.rstrip('/')
        if base_url.startswith('http://0.0.0.0') or base_url.startswith('https://0.0.0.0'):
            base_url = base_url.replace('0.0.0.0', 'localhost', 1)
        return jsonify({
            'message': 'Worker saved',
            'healthId': health_id,
            'qrUrl': f"{base_url}/api/workers/{health_id}/qr.png",
            'faceUrl': f"{base_url}/api/workers/{health_id}/face.png" if face_filename else None,
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/workers/<health_id>', methods=['GET'])
def get_worker(health_id: str):
    row = _read_worker(health_id)
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(row), 200


@app.route('/api/workers', methods=['GET'])
def list_workers():
    session: Session = SessionFactory()
    try:
        workers = session.query(DBWorker).order_by(DBWorker.registration_date.desc()).limit(200).all()
        return jsonify([
            {
                'health_id': w.health_id,
                'full_name': w.full_name,
                'age': w.age,
                'gender': w.gender,
                'phone': w.phone,
                'address': w.address,
                'native_state': w.native_state,
                'blood_group': w.blood_group,
                'marital_status': w.marital_status,
                'language': w.language,
                'financial_status': w.financial_status,
                'registration_date': (w.registration_date.strftime('%Y-%m-%d') if w.registration_date else ''),
            } for w in workers
        ]), 200
    finally:
        session.close()


@app.route('/api/appointments', methods=['POST'])
def create_appointment():
    data = request.get_json(silent=True) or {}
    health_id = (data.get('healthId') or '').strip()
    speciality = (data.get('speciality') or '').strip()
    requested_time = (data.get('requestedTime') or '').strip()
    if not health_id:
        return jsonify({'error': 'healthId required'}), 400
    session: Session = SessionFactory()
    try:
        w = session.query(DBWorker).filter_by(health_id=health_id).first()
        if not w:
            return jsonify({'error': 'Worker not found'}), 404
        appt = DBAppointment(worker_id=w.id, doctor_speciality=speciality or None, requested_time=requested_time or None, status='pending')
        session.add(appt)
        session.commit()
        return jsonify({'message': 'Appointment created'}), 201
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@app.route('/api/appointments', methods=['GET'])
def list_appointments():
    session: Session = SessionFactory()
    try:
        items = session.query(DBAppointment).order_by(DBAppointment.created_at.desc()).limit(200).all()
        out = []
        for a in items:
            out.append({
                'id': a.id,
                'workerHealthId': a.worker.health_id if a.worker else None,
                'workerName': a.worker.full_name if a.worker else None,
                'doctorId': a.doctor_id,
                'speciality': a.doctor_speciality,
                'status': a.status,
                'requestedTime': a.requested_time,
                'createdAt': a.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            })
        return jsonify(out), 200
    finally:
        session.close()


@app.route('/api/feedback', methods=['POST'])
def create_feedback():
    data = request.get_json(silent=True) or {}
    health_id = (data.get('healthId') or '').strip()
    rating = int(data.get('rating') or 0)
    message = (data.get('message') or '').strip()
    session: Session = SessionFactory()
    try:
        w = session.query(DBWorker).filter_by(health_id=health_id).first()
        if not w:
            return jsonify({'error': 'Worker not found'}), 404
        fb = DBFeedback(worker_id=w.id, rating=rating or None, message=message or None)
        session.add(fb)
        session.commit()
        return jsonify({'message': 'Feedback submitted'}), 201
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@app.route('/api/workers/<health_id>/qr.png', methods=['GET'])
def get_worker_qr(health_id: str):
    path = os.path.join(QR_IMAGE_DIR, f"{health_id}.png")
    if not os.path.exists(path):
        row = _read_worker(health_id)
        if not row:
            return jsonify({'error': 'Not found'}), 404
        # Rebuild QR if missing
        payload = json.dumps({
            'healthId': row['health_id'],
            'fullName': row['full_name'],
            'gender': row['gender'],
            'nativeState': row['native_state'],
            'registrationDate': row['registration_date'],
        }, ensure_ascii=False)
        _generate_qr_image(payload, health_id, row.get('face_filename') or None)
    return send_file(path, mimetype='image/png')


@app.route('/api/workers/<health_id>/face.png', methods=['GET'])
def get_worker_face(health_id: str):
    path = os.path.join(FACE_IMAGE_DIR, f"{health_id}.png")
    if not os.path.exists(path):
        return jsonify({'error': 'Not found'}), 404
    return send_file(path, mimetype='image/png')


@app.route('/api/generate-qr', methods=['GET'])
def generate_qr_generic():
    qr_data = request.args.get('data')
    if not qr_data:
        return jsonify({'error': 'No data provided'}), 400
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


if __name__ == '__main__':
    app.run(host=HOST, port=PORT, debug=DEBUG)
