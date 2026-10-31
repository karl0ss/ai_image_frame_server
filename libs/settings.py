import configparser
import hashlib
import re
from dataclasses import dataclass

from libs.generic import ConfigSingleton, _atomic_write, hash_password

BOOL, TEXT, INT, LIST, SECRET, TIME, URL = "bool", "text", "int", "list", "secret", "time", "url"

PASSWORD_FIELD = "frame:password_for_auth"
PASSWORD_CONFIRM_FIELD = "frame:password_for_auth_confirm"

_SECTION_RE = re.compile(r"^\[(?P<section>[^\]]+)\]")
_KEY_RE = re.compile(r"^(?P<key>[^\s#;\[=:][^=:]*?)\s*[=:]")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
_URL_RE = re.compile(r"^https?://\S+$")


@dataclass(frozen=True)
class Field:
    section: str
    key: str
    label: str
    kind: str = TEXT
    help: str = ""
    default: str = ""
    restart: bool = False
    required: bool = False
    minimum: int | None = None
    maximum: int | None = None

    @property
    def name(self) -> str:
        return f"{self.section}:{self.key}"


@dataclass(frozen=True)
class Group:
    title: str
    description: str
    fields: tuple[Field, ...]
    enabled_field: str = ""  # Collapsed until this bool field is on.


def _provider_fields(section: str, *extra: Field) -> tuple[Field, ...]:
    return (
        Field(section, "api_key", "API key", SECRET),
        Field(section, "models", "Models", LIST, "One per line."),
        *extra,
    )


GROUPS = (
    Group("Frame", "The web page, nightly run and login.", (
        Field("frame", "reload_interval", "Page refresh limit (ms)", INT,
              "The web page checks for a new image at this rate, or every 30 seconds if that's sooner.",
              default="30000", minimum=1000),
        Field("frame", "auto_regen", "Generate an image every day", BOOL, restart=True),
        Field("frame", "regen_time", "Daily generation time", TIME, "24-hour HH:MM.", default="03:00", restart=True),
        Field("frame", "create_requires_auth", "Require login to create images", BOOL),
        Field("frame", "password_for_auth", "Password", SECRET),
        Field("frame", "port", "Server port", INT,
              "Must match the container's port mapping.", default="5000", restart=True, minimum=1, maximum=65535),
    )),
    Group("Image generation", "ComfyUI and what gets rendered.", (
        Field("comfyui", "comfyui_url", "ComfyUI URL", URL, required=True),
        Field("comfyui", "output_dir", "Output folder", TEXT,
              "Must stay on the mounted volume, or images are lost when the container is recreated.",
              default="./output/", restart=True, required=True),
        Field("comfyui", "width", "Width", INT, minimum=64, maximum=8192),
        Field("comfyui", "height", "Height", INT, minimum=64, maximum=8192),
        Field("comfyui", "prompt", "Prompt request", TEXT, "The instruction sent to the prompt model."),
        Field("comfyui", "topics", "Topics", LIST, "One per line. A random one is used for random prompts."),
        Field("comfyui", "secondary_topic", "Secondary topic", TEXT, "Added to every prompt when set."),
        Field("comfyui", "flux", "Use Flux models", BOOL),
        Field("comfyui", "qwen", "Use Qwen models", BOOL),
        Field("comfyui", "only_flux", "Never pick SDXL at random", BOOL),
    )),
    Group("Image models", "File names as ComfyUI knows them, one per line.", (
        Field("comfyui", "models", "SDXL", LIST),
        Field("comfyui:flux", "models", "Flux", LIST),
        Field("comfyui:qwen", "models", "Qwen", LIST),
    )),
    Group("OpenWebUI", "Writes prompts. Used whenever it has models listed or every model is on.", (
        Field("openwebui", "base_url", "URL", URL),
        *_provider_fields("openwebui", Field("openwebui", "list_all_models", "Also use every model", BOOL)),
    )),
    Group("OpenRouter", "Writes prompts.", (
        Field("openrouter", "enabled", "Enabled", BOOL),
        *_provider_fields("openrouter", Field("openrouter", "list_all_free_models", "Also use every free model", BOOL)),
    ), enabled_field="openrouter:enabled"),
    Group("Ollama Cloud", "Writes prompts.", (
        Field("ollama", "enabled", "Enabled", BOOL),
        *_provider_fields("ollama", Field("ollama", "list_all_cloud_models", "Also use every cloud model", BOOL)),
    ), enabled_field="ollama:enabled"),
    Group("FreeLLMAPI", "Writes prompts, and can replace ComfyUI for images.", (
        Field("freellmapi", "enabled", "Enabled for prompts", BOOL),
        Field("freellmapi", "image_backend", "Use for images instead of ComfyUI", BOOL,
              'The router picks the model, so the model chosen on the create page is ignored.'),
        Field("freellmapi", "base_url", "URL", URL, "For example http://192.168.4.10:3005"),
        *_provider_fields("freellmapi"),
    ), enabled_field="freellmapi:enabled"),
    Group("Remote ComfyUI", "Starts the ComfyUI service over SSH before a render and stops it after.", (
        Field("remote", "enabled", "Enabled", BOOL, restart=True),
        Field("remote", "host", "Host", restart=True),
        Field("remote", "port", "SSH port", INT, default="22", restart=True, minimum=1, maximum=65535),
        Field("remote", "username", "Username", restart=True),
        Field("remote", "password", "Password", SECRET, restart=True),
        Field("remote", "service", "Service name", default="comfyui", restart=True),
        Field("remote", "startup_poll_timeout", "Startup wait (seconds)", INT,
              default="90", restart=True, minimum=1),
    ), enabled_field="remote:enabled"),
)


def read_config_text() -> str:
    try:
        with open(ConfigSingleton._path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def parse_config(text: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(text)
    return config


def text_version(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _extra_groups(config: configparser.ConfigParser) -> tuple[Group, ...]:
    """Settings in the file that aren't described above stay visible and editable."""
    known = {field.name for group in GROUPS for field in group.fields}
    fields = []
    for section in config.sections():
        for key in config[section]:
            if f"{section}:{key}" in known:
                continue
            secret = any(word in key for word in ("password", "key", "token", "secret"))
            fields.append(Field(section, key, f"{section} / {key}", SECRET if secret else TEXT))
    return (Group("Other settings", "In your config file, but not used by a known feature.", tuple(fields)),) if fields else ()


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,\n]", value) if item.strip()]


def _is_true(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes", "on")


def _current(config: configparser.ConfigParser, field: Field) -> str:
    return config.get(field.section, field.key, fallback=field.default)


def _validate(field: Field, value: str) -> str | None:
    if "\n" in value or "\r" in value:
        return "Must be a single line."
    if not value:
        # An empty number or time would stop the server from starting.
        return "This setting is required." if field.required or field.kind in (INT, TIME) else None
    if field.kind == INT:
        if not re.fullmatch(r"\d+", value):
            return "Must be a whole number."
        if field.minimum is not None and int(value) < field.minimum:
            return f"Must be at least {field.minimum}."
        if field.maximum is not None and int(value) > field.maximum:
            return f"Must be at most {field.maximum}."
    if field.kind == TIME and not _TIME_RE.match(value):
        return "Use 24-hour HH:MM, for example 03:30."
    if field.kind == URL and not _URL_RE.match(value):
        return "Must start with http:// or https://."
    return None


def collect_changes(config: configparser.ConfigParser, form) -> tuple[dict[Field, str], dict[str, str]]:
    """Compares the submitted form with the config. Returns (changes, errors by field name)."""
    changes: dict[Field, str] = {}
    errors: dict[str, str] = {}

    for group in GROUPS + _extra_groups(config):
        for field in group.fields:
            if field.name not in form:
                continue
            # Checkboxes post a hidden False followed by True when ticked, so the last one wins.
            raw = form.getlist(field.name)[-1]
            current = _current(config, field)

            if field.kind == SECRET:
                value = raw.strip()
                if not value:
                    continue
                error = _validate(field, value)
                if error:
                    errors[field.name] = error
                elif field.name == PASSWORD_FIELD:
                    if value != form.get(PASSWORD_CONFIRM_FIELD, "").strip():
                        errors[PASSWORD_CONFIRM_FIELD] = "The passwords don't match."
                    else:
                        changes[field] = hash_password(value)
                else:
                    changes[field] = value
            elif field.kind == BOOL:
                if _is_true(raw) != _is_true(current):
                    changes[field] = "True" if _is_true(raw) else "False"
            elif field.kind == LIST:
                items = _split_list(raw)
                if items != _split_list(current):
                    changes[field] = ",".join(items)
            else:
                value = raw.strip()
                if value == current.strip():
                    continue
                error = _validate(field, value)
                if error:
                    errors[field.name] = error
                else:
                    changes[field] = value

    return changes, errors


def update_config_text(text: str, values: dict[tuple[str, str], str]) -> str:
    """Applies (section, key) -> value to config text, leaving every other line untouched."""
    remaining = dict(values)
    output: list[str] = []
    section = None
    section_end: dict[str, int] = {}  # Where a new key goes: after the section's last setting.
    skipping_continuation = False

    for line in text.splitlines():
        if skipping_continuation:
            if line.strip() and line[0].isspace():
                continue
            skipping_continuation = False

        section_match = _SECTION_RE.match(line)
        key_match = _KEY_RE.match(line) if section else None
        if section_match:
            section = section_match.group("section")
            section_end[section] = len(output) + 1
        elif key_match:
            key = key_match.group("key").strip()
            target = (section, key.lower())
            if target in remaining:
                value = remaining.pop(target)
                line = f"{key} = {value}".rstrip()
                skipping_continuation = True
        output.append(line)
        # Comments are skipped: one just before a header belongs to the next section.
        if section is not None and line.strip() and not line.lstrip().startswith(("#", ";")):
            section_end[section] = len(output)

    new_sections: dict[str, list[str]] = {}
    for (target_section, key), value in remaining.items():
        new_line = f"{key} = {value}".rstrip()
        if target_section not in section_end:
            new_sections.setdefault(target_section, []).append(new_line)
            continue
        index = section_end[target_section]
        output.insert(index, new_line)
        for name, end in section_end.items():
            if end >= index:
                section_end[name] = end + 1

    for name, lines in new_sections.items():
        if output and output[-1].strip():
            output.append("")
        output.append(f"[{name}]")
        output.extend(lines)

    return "\n".join(output) + "\n"


def save_changes(text: str, changes: dict[Field, str]) -> None:
    """Writes changes, refusing to save a file that wouldn't read back with those exact values."""
    values = {(field.section, field.key): value for field, value in changes.items()}
    new_text = update_config_text(text, values)
    saved = parse_config(new_text)
    for (section, key), value in values.items():
        if saved.get(section, key, fallback=None) != value:
            raise ValueError(f"{section}/{key} did not save correctly.")
    _atomic_write(ConfigSingleton._path, new_text)
    ConfigSingleton.reset()


def build_groups(config: configparser.ConfigParser, form=None, errors: dict[str, str] | None = None) -> list[dict]:
    """Prepares the page. After a rejected save, form keeps what the user typed. Secrets are never echoed."""
    errors = errors or {}
    groups = []
    for group in GROUPS + _extra_groups(config):
        fields = []
        for field in group.fields:
            stored = _current(config, field)
            value = stored
            if form is not None and field.name in form and field.kind != SECRET:
                value = form.getlist(field.name)[-1]
            if field.kind == LIST:
                value = "\n".join(_split_list(value))
            fields.append({
                "name": field.name,
                "label": field.label,
                "kind": field.kind,
                "help": field.help,
                "restart": field.restart,
                "required": field.required,
                "value": "" if field.kind == SECRET else value,
                "checked": _is_true(value) if field.kind == BOOL else False,
                "is_set": bool(stored.strip()),
                "error": errors.get(field.name, ""),
                "confirm_error": errors.get(PASSWORD_CONFIRM_FIELD, "") if field.name == PASSWORD_FIELD else "",
            })
        enabled = next((f["checked"] for f in fields if f["name"] == group.enabled_field), True)
        groups.append({
            "title": group.title,
            "description": group.description,
            "fields": fields,
            "open": enabled or any(f["error"] or f["confirm_error"] for f in fields),
        })
    return groups
