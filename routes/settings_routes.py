import configparser
import io
from flask import Blueprint, render_template, request, redirect, url_for, session
from libs.generic import ConfigSingleton, _atomic_write

bp = Blueprint('settings_route', __name__)
CONFIG_PATH = "./user_config.cfg"

SENSITIVE_KEYS = {'password_for_auth', 'api_key', 'password'}
MODEL_SECTIONS = ('comfyui', 'comfyui:flux', 'comfyui:qwen')


@bp.route('/settings', methods=['GET', 'POST'])
def config_editor():
    if not session.get("authenticated"):
        return redirect(url_for("auth_routes.login", next=request.path))

    config = configparser.ConfigParser(interpolation=None)
    config.read(CONFIG_PATH)

    topics = config.get('comfyui', 'topics', fallback='').split(',')
    general_models = config.get('comfyui', 'models', fallback='').split(',')
    flux_models = config.get('comfyui:flux', 'models', fallback='').split(',')
    qwen_models = config.get('comfyui:qwen', 'models', fallback='').split(',')

    topics = [t.strip() for t in topics if t.strip()]
    general_models = [m.strip() for m in general_models if m.strip()]
    flux_models = [m.strip() for m in flux_models if m.strip()]
    qwen_models = [m.strip() for m in qwen_models if m.strip()]

    if request.method == 'POST':
        if 'new_topic' in request.form:
            new_topic = request.form.get('new_topic', '').strip()
            if new_topic and len(new_topic) <= 200 and new_topic not in topics:
                topics.append(new_topic)

        if 'delete_topic' in request.form:
            to_delete = request.form.getlist('delete_topic')
            topics = [topic for topic in topics if topic not in to_delete]

        if 'new_model' in request.form:
            new_model = request.form.get('new_model', '').strip()
            if new_model and len(new_model) <= 200:
                lowered = new_model.lower()
                target = flux_models if 'flux' in lowered else qwen_models if 'qwen' in lowered else general_models
                if new_model not in target:
                    target.append(new_model)

        if 'delete_model' in request.form:
            to_delete = request.form.getlist('delete_model')
            general_models = [m for m in general_models if m not in to_delete]
            flux_models = [m for m in flux_models if m not in to_delete]
            qwen_models = [m for m in qwen_models if m not in to_delete]

        if not config.has_section('comfyui'):
            config.add_section('comfyui')
        if not config.has_section('comfyui:flux'):
            config.add_section('comfyui:flux')
        if not config.has_section('comfyui:qwen'):
            config.add_section('comfyui:qwen')

        config.set('comfyui', 'models', ','.join(general_models))
        config.set('comfyui:flux', 'models', ','.join(flux_models))
        config.set('comfyui:qwen', 'models', ','.join(qwen_models))
        config.set('comfyui', 'topics', ','.join(topics))

        for section in config.sections():
            for key in config[section]:
                if key == 'models' and section in MODEL_SECTIONS:
                    continue
                if key == 'topics' and section == 'comfyui':
                    continue
                form_key = f"{section}:{key}"
                if form_key in request.form:
                    new_value = request.form[form_key]
                    if key in SENSITIVE_KEYS and new_value == "********":
                        continue
                    config[section][key] = new_value

        buffer = io.StringIO()
        config.write(buffer)
        _atomic_write(CONFIG_PATH, buffer.getvalue())
        ConfigSingleton.reset()

        return redirect(url_for('settings_route.config_editor'))

    filtered_config = {}
    for section in config.sections():
        items = {
            k: v for k, v in config[section].items()
            if not (
                (k == 'models' and section in MODEL_SECTIONS) or
                (k == 'topics' and section == 'comfyui')
            )
        }
        if items:
            filtered_config[section] = items

    return render_template(
        'settings.html',
        topics=sorted(topics, key=str.lower),
        models=sorted(general_models + flux_models + qwen_models, key=str.lower),
        config_sections=filtered_config.keys(),
        config_values=filtered_config,
        sensitive_keys=SENSITIVE_KEYS
    )