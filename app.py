from flask import Flask, request, jsonify
import os
from backend_logic import run_scraper_logic, run_analyzer_logic
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow frontend (GitHub Pages) to talk to backend

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


@app.route('/process', methods=['POST'])
def process_resume():
    if 'resume' not in request.files:
        return jsonify({"error": "No resume file selected."}), 400

    resume_file = request.files['resume']
    domain = request.form.get('domain', '').strip()
    location = request.form.get('location', '').strip()

    if resume_file.filename == '' or not domain or not location:
        return jsonify({"error": "Please upload a resume and enter both domain and location."}), 400

    resume_filepath = os.path.join(app.config['UPLOAD_FOLDER'], "uploaded_resume.pdf")
    resume_file.save(resume_filepath)

    scraper_success = run_scraper_logic(domain, location)
    if not scraper_success:
        return jsonify({"error": "Could not find any jobs for the specified domain/location. Please try another one."}), 400

    jobs_csv_path = "scraped_jobs.csv"
    matched_jobs = run_analyzer_logic(resume_filepath, jobs_csv_path)

    return jsonify({
        "domain": domain,
        "location": location,
        "matched_jobs": matched_jobs
    })


@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Backend is running!"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Use Render's dynamic PORT
    app.run(host="0.0.0.0", port=port, debug=False)
