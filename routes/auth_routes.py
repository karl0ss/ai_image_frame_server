import hmac
from flask import Blueprint, render_template, request, redirect, url_for, session
from libs.generic import hash_password

bp = Blueprint("auth_routes", __name__)
user_config = None

def init_app(config):
    global user_config
    user_config = config

def is_safe_url(target):
    from urllib.parse import urlparse, urljoin
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc

@bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") if request.method == "GET" else request.form.get("next")

    if next_url:
        from urllib.parse import urlparse
        parsed = urlparse(next_url)
        if parsed.scheme and parsed.scheme not in ("http", "https"):
            next_url = None
        if ".." in (next_url or ""):
            next_url = None

    if request.method == "POST":
        stored_value = user_config["frame"]["password_for_auth"]
        submitted_password = request.form.get("password", "")
        if submitted_password:
            input_hash = hash_password(submitted_password)
            if len(stored_value) == 64 and all(c in "0123456789abcdef" for c in stored_value.lower()):
                authenticated = hmac.compare_digest(input_hash, stored_value)
            else:
                authenticated = hmac.compare_digest(submitted_password, stored_value)
            if authenticated:
                session["authenticated"] = True
                if next_url and is_safe_url(next_url):
                    return redirect(next_url)
                return redirect(url_for("create_routes.create_image_page"))
        return redirect(url_for("auth_routes.login", next=next_url))

    return render_template("login.html", next=next_url)