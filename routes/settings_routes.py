from flask import Blueprint, render_template, request, redirect, url_for, session
import configparser
from libs.generic import load_topics_from_config, load_models_from_config

bp = Blueprint('settings_route', __name__)
CONFIG_PATH = "./user_config.cfg"

@bp.route('/settings', methods=['GET', 'POST'])
def config_editor():
    if not session.get("authenticated"):
        return redirect(url_for("auth_routes.login", next=request.path))

    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)

    topics = config.get('comfyui', 'topics', fallback='').split(',')
    general_models = config.get('comfyui', 'models', fallback='').split(',')
    flux_models = config.get('comfyui:flux', 'models', fallback='').split(',')

    topics = [t.strip() for t in topics if t.strip()]
    general_models = [m.strip() for m in general_models if m.strip()]
    flux_models = [m.strip() for m in flux_models if m.strip()]

    if request.method == 'POST':
        if 'new_topic' in request.form:
            new_topic = request.form.get('new_topic', '').strip()
            if new_topic and new_topic not in topics:
                topics.append(new_topic)

        if 'delete_topic' in request.form:
            to_delete = request.form.getlist('delete_topic')
            topics = [topic for topic in topics if topic not in to_delete]

        if 'new_model' in request.form:
            new_model = request.form.get('new_model', '').strip()
            if new_model:
                if 'flux' in new_model and new_model not in flux_models:
                    flux_models.append(new_model)
                elif 'flux' not in new_model and new_model not in general_models:
                    general_models.append(new_model)

        if 'delete_model' in request.form:
            to_delete = request.form.getlist('delete_model')
            general_models = [m for m in general_models if m not in to_delete]
            flux_models = [m for m in flux_models if m not in to_delete]

        # Save models/topics into the shared config object
        if not config.has_section('comfyui'):
            config.add_section('comfyui')
        if not config.has_section('comfyui:flux'):
            config.add_section('comfyui:flux')

        config.set('comfyui', 'models', ','.join(general_models))
        config.set('comfyui:flux', 'models', ','.join(flux_models))
        config.set('comfyui', 'topics', ','.join(topics))

        # Handle dynamic CFG field updates (excluding DEFAULT and protected keys)
        for section in config.sections():
            for key in config[section]:
                if key == 'models' and section in ('comfyui', 'comfyui:flux'):
                    continue
                if key == 'topics' and section == 'comfyui':
                    continue
                form_key = f"{section}:{key}"
                if form_key in request.form:
                    new_value = request.form[form_key]
                    # Prevent overwriting masked secrets unless actually changed
                    if key in ('password_for_auth', 'api_key') and new_value == "********":
                        continue  # Skip overwriting
                    config[section][key] = new_value


        # Save everything at once
        with open(CONFIG_PATH, 'w') as configfile:
            config.write(configfile)

        return redirect(url_for('settings_route.config_editor'))

    # Prepare filtered config for display
    filtered_config = {}
    for section in config.sections():
        items = {
            k: v for k, v in config[section].items()
            if not (
                (k == 'models' and section in ('comfyui', 'comfyui:flux')) or
                (k == 'topics' and section == 'comfyui')
            )
        }
        if items:  # only include non-empty sections
            filtered_config[section] = items

    return render_template(
        'settings.html',
        topics=sorted(topics,key=str.lower),
        models=sorted(general_models + flux_models,key=str.lower),
        config_sections=filtered_config.keys(),
        config_values=filtered_config
    )
