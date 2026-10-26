"""Validated, atomic JSON persistence for local workbench projects."""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


PROJECT_ID_RE = re.compile(r"^project_[a-f0-9]{12}$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MAX_PROJECT_BYTES = 2 * 1024 * 1024
MAX_MESSAGES = 500
MAX_ELEMENTS = 2000
MAX_REFERENCES = 500
REFERENCE_KEYS = {"path", "url", "model_url", "meshUrl", "preview_url", "assetUrl", "viewerUrl"}
ELEMENT_TYPES = {"preview", "model", "note", "image", "stroke", "text", "primitive"}
PRIMITIVE_KINDS = {"sphere", "cube", "cone", "cylinder", "torus", "crystal", "capsule", "heart"}


class ProjectValidationError(ValueError):
    pass


def _finite_number(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectValidationError(f"{label} must be a number")
    if not (-1_000_000 <= value <= 1_000_000):
        raise ProjectValidationError(f"{label} is outside the supported range")


def _validate_reference(value: Any, data_root: Path) -> None:
    if not isinstance(value, str) or len(value) > 4096:
        raise ProjectValidationError("media references must be short local paths")
    parsed = urlsplit(value)
    decoded_path = unquote(parsed.path)
    parts = decoded_path.split("/")
    if (
        not parsed.scheme and not parsed.netloc and not parsed.query and not parsed.fragment
        and len(parts) == 6 and parts[1:3] == ["api", "projects"]
        and PROJECT_ID_RE.fullmatch(parts[3])
        and parts[4] == "media"
        and re.fullmatch(r"[a-f0-9]{32}\.(png|jpg|webp)", parts[5])
    ):
        candidate = (data_root / "projects" / parts[3] / "media" / parts[5]).resolve()
        if not candidate.is_relative_to((data_root / "projects" / parts[3] / "media").resolve()):
            raise ProjectValidationError("media reference escapes the application data directory")
        return
    if (
        parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
        or len(parts) < 5 or parts[1] != "api" or parts[2] != "data"
        or not SESSION_ID_RE.fullmatch(parts[3])
        or any(part in ("", ".", "..") for part in parts[4:])
        or "\\" in decoded_path or "\x00" in decoded_path
    ):
        raise ProjectValidationError("media references must stay inside /api/data/{session_id}")
    candidate = data_root.joinpath(parts[3], *parts[4:]).resolve()
    root = data_root.resolve()
    if not candidate.is_relative_to(root):
        raise ProjectValidationError("media reference escapes the application data directory")


def validate_project(
    source: dict[str, Any],
    data_root: Path,
    *,
    expected_id: str | None = None,
    allow_missing_id: bool = False,
) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise ProjectValidationError("project must be a JSON object")
    project = json.loads(json.dumps(source, ensure_ascii=False, allow_nan=False))
    project_id = project.get("id")
    if project_id is None and allow_missing_id:
        project_id = f"project_{uuid.uuid4().hex[:12]}"
    if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
        raise ProjectValidationError("invalid project id")
    if expected_id is not None and project_id != expected_id:
        raise ProjectValidationError("project id does not match the requested resource")
    project["id"] = project_id

    version = project.get("schemaVersion", 1)
    if version != 1:
        raise ProjectValidationError("unsupported project schemaVersion")

    name = project.get("name", "我的创作")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ProjectValidationError("project name must contain 1 to 80 characters")
    project["name"] = name.strip()
    project["schemaVersion"] = 1
    prompt = project.get("prompt", "")
    if not isinstance(prompt, str) or len(prompt) > 20_000:
        raise ProjectValidationError("prompt is too long")
    project["prompt"] = prompt

    for field, limit in (("messages", MAX_MESSAGES), ("previews", MAX_REFERENCES), ("versions", MAX_REFERENCES)):
        value = project.get(field, [])
        if not isinstance(value, list) or len(value) > limit:
            raise ProjectValidationError(f"{field} must be a list with at most {limit} entries")
        project[field] = value

    for message in project["messages"]:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant", "system"}:
            raise ProjectValidationError("messages require a valid role")
        content = message.get("content", "")
        if not isinstance(content, str) or len(content) > 20_000:
            raise ProjectValidationError("message content is too long")

    canvas = project.get("canvas", {})
    if not isinstance(canvas, dict):
        raise ProjectValidationError("canvas must be an object")
    elements = canvas.get("elements", [])
    if not isinstance(elements, list) or len(elements) > MAX_ELEMENTS:
        raise ProjectValidationError(f"canvas.elements must contain at most {MAX_ELEMENTS} entries")
    for element in elements:
        if not isinstance(element, dict) or element.get("type") not in ELEMENT_TYPES:
            raise ProjectValidationError("canvas elements require a supported type")
        for coordinate in ("x", "y", "width", "height"):
            if coordinate in element:
                _finite_number(element[coordinate], f"canvas element {coordinate}")
        if "text" in element and (not isinstance(element["text"], str) or len(element["text"]) > 20_000):
            raise ProjectValidationError("canvas element text is too long")
    project["canvas"] = canvas
    viewport = canvas.get("viewport", {})
    if not isinstance(viewport, dict):
        raise ProjectValidationError("canvas.viewport must be an object")
    for coordinate in ("x", "y"):
        if coordinate in viewport:
            _finite_number(viewport[coordinate], f"canvas viewport {coordinate}")
    if "zoom" in viewport:
        _finite_number(viewport["zoom"], "canvas viewport zoom")
        if not 0.1 <= viewport["zoom"] <= 4:
            raise ProjectValidationError("canvas viewport zoom must be between 0.1 and 4")
    editor = project.get("editor", {})
    if not isinstance(editor, dict):
        raise ProjectValidationError("editor must be an object")
    primitives = editor.get("primitives", [])
    if not isinstance(primitives, list) or len(primitives) > MAX_ELEMENTS:
        raise ProjectValidationError("editor.primitives must be a bounded list")
    for primitive in primitives:
        if not isinstance(primitive, dict) or primitive.get("kind") not in PRIMITIVE_KINDS:
            raise ProjectValidationError("editor contains an unsupported primitive")
        for coordinate in ("x", "y", "z", "rx", "ry", "rz", "scale"):
            if coordinate in primitive:
                _finite_number(primitive[coordinate], f"editor primitive {coordinate}")
        color = primitive.get("color")
        if color is not None and (not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color)):
            raise ProjectValidationError("editor primitive color must be a hex RGB value")
    project["editor"] = editor

    selection = project.get("selection")
    if selection is not None and not isinstance(selection, dict):
        raise ProjectValidationError("selection must be an object or null")
    if selection:
        index = selection.get("image_index")
        if index is not None and (isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 9):
            raise ProjectValidationError("selection.image_index must be between 0 and 9")
        session_id = selection.get("session_id")
        if session_id is not None and (not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id)):
            raise ProjectValidationError("selection.session_id is invalid")

    version_ids = set()
    for version in project["versions"]:
        if not isinstance(version, dict):
            raise ProjectValidationError("model versions must be objects")
        version_id = version.get("id") or version.get("sid")
        session_id = version.get("sid")
        if not isinstance(version_id, str) or not SESSION_ID_RE.fullmatch(version_id):
            raise ProjectValidationError("model version id is invalid")
        if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
            raise ProjectValidationError("model version session id is invalid")
        if version_id in version_ids:
            raise ProjectValidationError("model version ids must be unique")
        version_ids.add(version_id)
        version_prompt = version.get("prompt", "")
        if not isinstance(version_prompt, str) or len(version_prompt) > 20_000:
            raise ProjectValidationError("model version prompt is too long")
        version_primitives = version.get("primitives", [])
        if not isinstance(version_primitives, list) or len(version_primitives) > MAX_ELEMENTS:
            raise ProjectValidationError("model version primitives must be a bounded list")
        for primitive in version_primitives:
            if not isinstance(primitive, dict) or primitive.get("kind") not in PRIMITIVE_KINDS:
                raise ProjectValidationError("model version contains an unsupported primitive")
            for coordinate in ("x", "y", "z", "rx", "ry", "rz", "scale"):
                if coordinate in primitive:
                    _finite_number(primitive[coordinate], f"model version primitive {coordinate}")
    active_version_id = project.get("activeVersionId")
    if active_version_id is not None and active_version_id not in version_ids:
        raise ProjectValidationError("activeVersionId must reference a saved model version")

    reference_count = 0

    def check_references(value: Any) -> None:
        nonlocal reference_count
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in REFERENCE_KEYS and nested is not None:
                    _validate_reference(nested, data_root)
                    reference_count += 1
                else:
                    check_references(nested)
        elif isinstance(value, list):
            for nested in value:
                check_references(nested)

    check_references(project)
    if reference_count > MAX_REFERENCES:
        raise ProjectValidationError(f"project has more than {MAX_REFERENCES} media references")
    if len(json.dumps(project, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_PROJECT_BYTES:
        raise ProjectValidationError("project document exceeds 2 MB")
    return project


class ProjectStore:
    def __init__(self, data_root: str | os.PathLike[str]):
        self.data_root = Path(data_root).resolve()
        self.root = self.data_root / "projects"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, project_id: str) -> Path:
        if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
            raise ProjectValidationError("invalid project id")
        path = (self.root / f"{project_id}.json").resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ProjectValidationError("invalid project id")
        return path

    def create(self, source: dict[str, Any]) -> dict[str, Any]:
        if "id" in source:
            raise ProjectValidationError("new projects must not choose an id")
        project = validate_project(source, self.data_root, allow_missing_id=True)
        project["createdAt"] = int(time.time())
        self._write(project)
        return project

    def list(self) -> list[dict[str, Any]]:
        items = []
        for path in self.root.glob("project_*.json"):
            try:
                project = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            items.append({
                "id": project.get("id"),
                "name": project.get("name"),
                "updatedAt": project.get("updatedAt"),
                "versionCount": len(project.get("versions", [])),
                "legacyId": project.get("legacyId"),
            })
        return sorted(items, key=lambda item: item.get("updatedAt", 0), reverse=True)

    def read(self, project_id: str) -> dict[str, Any] | None:
        path = self._path(project_id)
        if not path.is_file():
            return None
        try:
            project = validate_project(json.loads(path.read_text(encoding="utf-8")), self.data_root, expected_id=project_id)
        except (OSError, json.JSONDecodeError, ProjectValidationError):
            return None
        missing = []
        for reference in self._references(project):
            parsed = urlsplit(reference)
            path_parts = unquote(parsed.path).split("/")
            if path_parts[1:3] == ["api", "projects"]:
                target = self.data_root.joinpath("projects", path_parts[3], *path_parts[4:]).resolve()
            else:
                target = self.data_root.joinpath(path_parts[3], *path_parts[4:]).resolve()
            if not target.is_file():
                missing.append(reference)
        project["missingReferences"] = missing
        return project

    def update(self, project_id: str, source: dict[str, Any]) -> dict[str, Any] | None:
        if not self._path(project_id).is_file():
            return None
        project = validate_project(source, self.data_root, expected_id=project_id)
        existing = self.read(project_id)
        if existing:
            project.setdefault("createdAt", existing.get("createdAt"))
        self._write(project)
        return project

    def delete(self, project_id: str) -> bool:
        path = self._path(project_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def _write(self, project: dict[str, Any]) -> None:
        project["updatedAt"] = int(time.time())
        target = self._path(project["id"])
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".project-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(project, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    @staticmethod
    def _references(project: dict[str, Any]) -> list[str]:
        references: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    if key in REFERENCE_KEYS and isinstance(nested, str):
                        references.append(nested)
                    else:
                        visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        visit(project)
        return references
