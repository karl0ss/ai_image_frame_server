from flask import Blueprint, jsonify, send_file
import os
from libs.generic import get_favourites, favourites_file

bp = Blueprint("favourites_routes", __name__)

@bp.route("/favourites/download", methods=["GET"])
def download_favourites():
    """
    Route to return the favourites.json file as download
    """
    if os.path.exists(favourites_file):
        return send_file(favourites_file, mimetype='application/json', as_attachment=True, download_name='favourites.json')
    else:
        # If the file doesn't exist, return an empty array as JSON
        return jsonify([])