from flask import Blueprint, jsonify
from libs import jobs
from libs.comfyui import cancel_current_job, get_queue_details
from routes.auth_routes import requires_create_auth

bp = Blueprint("job_routes", __name__)

@bp.route("/cancel", methods=["POST"])
@requires_create_auth
def cancel_job():
    return cancel_current_job()

@bp.route("/api/queue", methods=["GET"])
def api_queue():
    return jsonify(get_queue_details())

@bp.route("/api/jobs/<job_id>", methods=["GET"])
def api_job(job_id):
    job = jobs.get_job(job_id)
    if job is None:
        return jsonify({"error": "Unknown job"}), 404
    return jsonify(job)