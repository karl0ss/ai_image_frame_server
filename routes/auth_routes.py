import functools
from flask import Blueprint, flash, render_template, request, redirect, url_for, session
from libs.generic import get_bool, load_config, verify_password

bp = Blueprint("auth_routes", __name__)


def requires_create_auth(view):
    """Guards image creation and job control when create_requires_auth is on."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if get_bool(load_config(), "frame", "create_requires_auth", False) and not session.get("authenticated"):
            next_url = request.path if request.method == "GET" else url_for("create_routes.create_image_page")
            return redirect(url_for("auth_routes.login", next=next_url))
        return view(*args, **kwargs)
    return wrapped


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
        stored_value = load_config()["frame"]["password_for_auth"]
        submitted_password = request.form.get("password", "")
        if submitted_password and verify_password(submitted_password, stored_value):
            session["authenticated"] = True
            if next_url and is_safe_url(next_url):
                return redirect(next_url)
            return redirect(url_for("create_routes.create_image_page"))
        flash("Incorrect password.", "error")
        return redirect(url_for("auth_routes.login", next=next_url))

    return render_template("login.html", next=next_url)