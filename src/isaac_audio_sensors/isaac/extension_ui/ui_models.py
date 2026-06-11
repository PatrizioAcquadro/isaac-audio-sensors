"""Defensive adapters around ``omni.ui`` models and windows."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Any


def _new_simple_model(ui: Any, kind: str, value: Any) -> Any:
    model_type_name = {
        "bool": "SimpleBoolModel",
        "float": "SimpleFloatModel",
        "int": "SimpleIntModel",
        "string": "SimpleStringModel",
    }[kind]
    model_type = getattr(ui, model_type_name, None)
    if model_type is None:
        return None
    try:
        return model_type(value)
    except TypeError:
        model = model_type()
        _set_model_value(model, value)
        return model


def _ui_fraction(ui: Any, value: int) -> Any:
    fraction = getattr(ui, "Fraction", None)
    if fraction is None:
        return value
    try:
        return fraction(value)
    except Exception:
        return value


def _format_edit_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _set_model_value(model: Any, value: Any) -> None:
    if model is None:
        return
    if hasattr(model, "set_value"):
        model.set_value(value)


def _set_combo_index(model: Any, index: int) -> None:
    if model is None:
        return
    if hasattr(model, "get_item_value_model"):
        item_model = model.get_item_value_model()
        if item_model is not None:
            _set_model_value(item_model, index)
            return
    _set_model_value(model, index)


def _model_string(model: Any) -> str:
    if model is None:
        return ""
    if hasattr(model, "get_value_as_string"):
        return str(model.get_value_as_string())
    if hasattr(model, "as_string"):
        return str(model.as_string)
    return str(getattr(model, "value", ""))


def _model_float(model: Any) -> float:
    text = _model_string(model).strip()
    if text != "":
        return float(text)
    get_value = getattr(model, "get_value_as_float", None)
    if callable(get_value):
        try:
            return float(get_value())
        except (TypeError, ValueError):
            pass
    try:
        as_float = model.as_float
    except (AttributeError, TypeError, ValueError):
        pass
    else:
        try:
            return float(as_float)
        except (TypeError, ValueError):
            pass
    raise ValueError("empty numeric value")


def _model_int(model: Any) -> int:
    text = _model_string(model).strip()
    if text != "":
        return int(float(text))
    get_value = getattr(model, "get_value_as_int", None)
    if callable(get_value):
        try:
            return int(get_value())
        except (TypeError, ValueError):
            pass
    try:
        as_int = model.as_int
    except (AttributeError, TypeError, ValueError):
        pass
    else:
        try:
            return int(as_int)
        except (TypeError, ValueError):
            pass
    raise ValueError("empty integer value")


def _model_bool(model: Any) -> bool:
    if hasattr(model, "get_value_as_bool"):
        return bool(model.get_value_as_bool())
    if hasattr(model, "as_bool"):
        return bool(model.as_bool)
    return bool(getattr(model, "value", False))


def _combo_index(model: Any) -> int:
    if hasattr(model, "get_item_value_model"):
        value_model = model.get_item_value_model()
        try:
            as_int = value_model.as_int
        except (AttributeError, TypeError, ValueError):
            pass
        else:
            return int(as_int)
        get_value = getattr(value_model, "get_value_as_int", None)
        if callable(get_value):
            return int(get_value())
    return _model_int(model)


def _window_visible(window: Any | None) -> bool:
    if window is None:
        return False
    visible = getattr(window, "visible", None)
    if visible is None:
        return True
    return bool(visible)


def _set_window_visible(window: Any, visible: bool) -> bool:
    try:
        window.visible = visible
        return True
    except Exception:
        pass
    method_name = "show" if visible else "hide"
    method = getattr(window, method_name, None)
    if callable(method):
        try:
            method()
            return True
        except Exception:
            return False
    return False


def _focus_window(window: Any) -> None:
    for method_name in ("focus", "bring_to_front"):
        method = getattr(window, method_name, None)
        if callable(method):
            with suppress(Exception):
                method()
            return


def _set_window_visibility_changed_fn(
    window: Any,
    callback: Callable[[bool], None],
) -> None:
    setter = getattr(window, "set_visibility_changed_fn", None)
    if not callable(setter):
        return
    with suppress(Exception):
        setter(callback)


def _normalize_hotkey_setting(value: str) -> str:
    normalized = value.strip()
    if normalized.lower() in {"", "none", "disabled", "off", "false"}:
        return ""
    return normalized
