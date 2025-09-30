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

# CSV schema
FIELDNAMES = [
    'health_id', 'full_name', 'age', 'gender', 'phone', 'address', 'native_state',
    'blood_group', 'marital_status', 'language', 'financial_status',
    'registration_date', 'face_filename', 'qr_filename'
]

# Ensure CSV exists with header
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app, resources={r"/*": {"origins": CORS_ORIGINS}})


def _save_face_image(health_id: str, face_b64_data: str) -> str:
	"""Save base64 image to FACE_IMAGE_DIR and return filename."""
	try:
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
				thumb_size = max(64, qr_img.size[0] // 6)
				face_img.thumbnail((thumb_size, thumb_size))
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
	if not os.path.exists(CSV_FILE):
		return None
	with open(CSV_FILE, mode='r', newline='', encoding='utf-8') as file:
		reader = csv.DictReader(file)
		for row in reader:
			if row['health_id'] == health_id:
				return row
	return None


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

		registration_date = data.get('registrationDate') or datetime.utcnow().strftime('%Y-%m-%d')
		face_b64 = data.get('faceImage')

		# Save face image
		face_filename = _save_face_image(health_id, face_b64) if face_b64 else ''

		# QR content: JSON payload
		qr_payload = {
			'healthId': health_id,
			'fullName': full_name,
			'gender': gender,
			'address': address,
			'nativeState': native_state,
			'bloodGroup': blood_group,
			'maritalStatus': marital_status,
			'financialStatus': financial_status,
			'registrationDate': registration_date,
		}
		qr_text = json.dumps(qr_payload, ensure_ascii=False)
		qr_filename = _generate_qr_image(qr_text, health_id, face_filename or None)

		# Persist to CSV (idempotent upsert by health_id)
		rows = []
		exists = False
		if os.path.exists(CSV_FILE):
			with open(CSV_FILE, mode='r', newline='', encoding='utf-8') as f:
				reader = csv.DictReader(f)
				for row in reader:
					if row['health_id'] == health_id:
						row = {
							'health_id': health_id,
							'full_name': full_name,
							'age': str(age),
							'gender': gender,
							'phone': phone,
							'address': address,
							'native_state': native_state,
							'blood_group': blood_group,
							'marital_status': marital_status,
							'language': language,
							'financial_status': financial_status,
							'registration_date': registration_date,
							'face_filename': face_filename,
							'qr_filename': qr_filename,
						}
						exists = True
					rows.append(row)
		if not exists:
			rows.append({
				'health_id': health_id,
				'full_name': full_name,
				'age': str(age),
				'gender': gender,
				'phone': phone,
				'address': address,
				'native_state': native_state,
				'blood_group': blood_group,
				'marital_status': marital_status,
				'language': language,
				'financial_status': financial_status,
				'registration_date': registration_date,
				'face_filename': face_filename,
				'qr_filename': qr_filename,
			})
		with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
			writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
			writer.writeheader()
			writer.writerows(rows)

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


@app.route('/api/workers/<health_id>/qr.png', methods=['GET'])
def get_worker_qr(health_id: str):
	path = os.path.join(QR_IMAGE_DIR, f"{health_id}.png")
	if not os.path.exists(path):
		row = _read_worker(health_id)
		if not row:
			return jsonify({'error': 'Not found'}), 404
		# Rebuild QR if missing
		payload = json.dumps({
			'healthId': row.get('health_id', ''),
			'fullName': row.get('full_name', ''),
			'gender': row.get('gender', ''),
			'address': row.get('address', ''),
			'nativeState': row.get('native_state', ''),
			'bloodGroup': row.get('blood_group', ''),
			'maritalStatus': row.get('marital_status', ''),
			'financialStatus': row.get('financial_status', ''),
			'registrationDate': row.get('registration_date', ''),
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


