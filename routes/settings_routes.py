from flask import Blueprint, render_template, request, redirect, url_for, session
import configparser
from libs.generic import load_topics_from_config

bp = Blueprint('settings_route', __name__)
CONFIG_PATH = "./user_config.cfg"

def save_items(items):
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)

    # Make sure the section exists
    if not config.has_section('comfyui'):
        config.add_section('comfyui')

    # Save updated list to the 'topics' key
    config.set('comfyui', 'topics', ', '.join(items))

    with open(CONFIG_PATH, 'w') as configfile:
        config.write(configfile)

@bp.route('/settings', methods=['GET', 'POST'])
def config_editor():
    if not session.get("authenticated"):
        return redirect(url_for("auth_routes.login", next=request.path))
    items = load_topics_from_config()  # should return list[str]

    if request.method == 'POST':
        if 'new_topic' in request.form:
            new_item = request.form.get('new_topic', '').strip()
            if new_item and new_item not in items:
                items.append(new_item)
        elif 'delete_topic' in request.form:
            to_delete = request.form.getlist('delete_topic')
            items = [item for item in items if item not in to_delete]

        save_items(items)
        return redirect(url_for('settings_route.config_editor'))

    return render_template('settings.html', topics=items)
