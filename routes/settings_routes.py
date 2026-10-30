from flask import Blueprint, flash, render_template, request, redirect, url_for, session
from libs.settings import (
    build_groups, collect_changes, parse_config, read_config_text, save_changes, text_version
)

bp = Blueprint('settings_route', __name__)


def _render(text: str, form=None, errors=None, status: int = 200):
    groups = build_groups(parse_config(text), form, errors)
    return render_template("settings.html", groups=groups, config_version=text_version(text)), status


@bp.route('/settings', methods=['GET', 'POST'])
def config_editor():
    if not session.get("authenticated"):
        return redirect(url_for("auth_routes.login", next=request.path))

    text = read_config_text()
    if request.method == 'GET':
        return _render(text)

    # Without this, a stale tab would silently undo changes made elsewhere.
    if request.form.get("config_version") != text_version(text):
        flash("The config file changed since this page loaded. Check your edits and save again.", "error")
        return _render(text, form=request.form, status=409)

    changes, errors = collect_changes(parse_config(text), request.form)
    if errors:
        flash(f"Nothing was saved. Fix the {len(errors)} highlighted setting(s).", "error")
        return _render(text, form=request.form, errors=errors, status=400)

    if not changes:
        flash("No changes to save.", "info")
        return redirect(url_for('settings_route.config_editor'))

    try:
        save_changes(text, changes)
    except (OSError, ValueError) as e:
        flash(f"Could not save: {e}", "error")
        return _render(text, form=request.form, status=500)

    flash(f"Saved {len(changes)} setting(s).", "success")
    restart = sorted({field.label for field in changes if field.restart})
    if restart:
        flash(f"Restart the server to apply: {', '.join(restart)}.", "warning")
    return redirect(url_for('settings_route.config_editor'))
