from flask import Blueprint, jsonify, send_file
import os
import json

bp = Blueprint("favourites_routes", __name__)
favourites_file = "./favourites.json"

def get_favourites():
    if not os.path.exists(favourites_file):
        return []
    with open(favourites_file, 'r') as f:
        return json.load(f)

@bp.route("/favourites", methods=["GET"])
def favourites():
    """
    Route to return the favourites.json file
    """
    if os.path.exists(favourites_file):
        return send_file(favourites_file, mimetype='application/json')
    else:
        # If the file doesn't exist, return an empty array as JSON
        return jsonify([])