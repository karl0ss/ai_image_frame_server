from flask import Blueprint
from libs.comfyui import cancel_current_job

bp = Blueprint("job_routes", __name__)

@bp.route("/cancel", methods=["GET"])
def cancel_job():
    return cancel_current_job()
