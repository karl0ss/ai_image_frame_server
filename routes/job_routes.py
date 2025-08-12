from flask import Blueprint, jsonify
from libs.comfyui import cancel_current_job, get_queue_details

bp = Blueprint("job_routes", __name__)

@bp.route("/cancel", methods=["GET"])
def cancel_job():
    return cancel_current_job()

@bp.route("/api/queue", methods=["GET"])
def api_queue():
    return jsonify(get_queue_details())
