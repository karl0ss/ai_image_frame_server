from flask import Blueprint, render_template, request, redirect, url_for, session
from libs.generic import load_models_from_config, load_topics_from_config
from urllib.parse import urlparse, urljoin

bp = Blueprint("auth_routes", __name__)
user_config = None

def init_app(config):
    global user_config
    user_config = config

def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc

@bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") if request.method == "GET" else request.form.get("next")

    if request.method == "POST":
        if request.form["password"] == user_config["frame"]["password_for_auth"]:
            session["authenticated"] = True
            if next_url and is_safe_url(next_url):
                return redirect(next_url)
            return redirect(url_for("create_image"))  # fallback
        return redirect(url_for("auth_routes.login", next=next_url))  # retry with `next`
    
    return render_template("login.html", next=next_url)