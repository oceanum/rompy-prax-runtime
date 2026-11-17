"""Pure, reference-derived limits used to prepare future bounded-profile work.

This module is deliberately not connected to public admission or generation until
workbench issue #5 integrates the evidence verifier.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import re

POLICY_ID = "reference-subsets-v1"
EXPECTED_FILE = ".rompy-expected-outputs.json"
_EPSILON = 1e-9
_PATHS = (
    ("period", "start"),
    ("period", "duration"),
    ("period", "interval"),
    *(
        ("config", "cgrid", "grid", key)
        for key in ("xp", "yp", "xlen", "ylen", "mx", "my")
    ),
    ("config", "output", "points", "xp"),
    ("config", "output", "points", "yp"),
)


class PolicyError(ValueError):
    """Value-free policy refusal."""


def _refuse():
    raise PolicyError("configuration_policy_failed")


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        _refuse()
    return value


def _hours(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]?[hd]", value):
        _refuse()
    hours = int(value[:-1]) * (24 if value[-1] == "d" else 1)
    if not 1 <= hours <= 24:
        _refuse()
    return hours


def _start(value):
    if not isinstance(value, str):
        _refuse()
    try:
        start = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if start.minute or start.second or start.microsecond:
            _refuse()
        if start.tzinfo is not None and start.utcoffset() != timedelta(0):
            _refuse()
        return start.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError):
        _refuse()


def same(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            same(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return left == right


def validate(document, reference):
    """Check authored allowlist, bounds and time before constructing library models."""
    candidate = deepcopy(document)
    try:
        for path in _PATHS:
            left, right = candidate, reference
            for key in path[:-1]:
                left, right = left[key], right[key]
            if path[-1] not in left:
                raise KeyError
            left[path[-1]] = deepcopy(right[path[-1]])
        if not same(candidate, reference):
            raise PolicyError("unsupported_configuration_change")
        period, base_period = document["period"], reference["period"]
        start, base_start = _start(period["start"]), _start(base_period["start"])
        duration, interval = _hours(period["duration"]), _hours(period["interval"])
        end = start + timedelta(hours=duration)
        if (
            duration % interval
            or not base_start
            <= start
            < end
            <= base_start + timedelta(hours=_hours(base_period["duration"]))
        ):
            _refuse()
        if duration // interval + 1 > 25:
            _refuse()
        grid, base = (
            document["config"]["cgrid"]["grid"],
            reference["config"]["cgrid"]["grid"],
        )
        for key in ("xp", "yp", "xlen", "ylen"):
            _number(grid[key])
        if grid["xlen"] <= 0 or grid["ylen"] <= 0:
            _refuse()
        for key in ("mx", "my"):
            if type(grid[key]) is not int or not 1 <= grid[key] <= base[key]:
                _refuse()
        points = document["config"]["output"]["points"]
        xs, ys = points["xp"], points["yp"]
        if (
            type(xs) is not list
            or type(ys) is not list
            or not 1 <= len(xs) == len(ys) <= 3
        ):
            _refuse()
        for x, y in zip(xs, ys):
            _number(x)
            _number(y)
    except PolicyError:
        raise
    except (KeyError, TypeError, OverflowError):
        raise PolicyError("unsupported_configuration_change") from None
    return {"start": start, "end": end, "instants": duration // interval + 1}


def effective_document(document, reference):
    """Detached, coherent UTC-naive model input; authored document stays untouched."""
    validate(document, reference)
    result = deepcopy(document)
    period = result["period"]
    start = _start(period["start"]).replace(tzinfo=None)
    duration, interval = _hours(period["duration"]), _hours(period["interval"])
    period["start"] = start.isoformat(timespec="seconds")
    period["duration"] = f"{duration}h"
    period["interval"] = f"{interval}h"
    return result


def _polygon(grid):
    from shapely.geometry import Polygon

    x, y = grid.x, grid.y
    if x.ndim != 2 or y.ndim != 2 or x.shape != y.shape or x.size < 4:
        _refuse()
    if not all(math.isfinite(float(v)) for v in x.flat) or not all(
        math.isfinite(float(v)) for v in y.flat
    ):
        _refuse()
    if len(set(zip(x.ravel().tolist(), y.ravel().tolist()))) != x.size:
        _refuse()
    column_x, column_y = x[:, 1:] - x[:, :-1], y[:, 1:] - y[:, :-1]
    row_x, row_y = x[1:, :] - x[:-1, :], y[1:, :] - y[:-1, :]
    if (column_x**2 + column_y**2).min() <= 0 or (row_x**2 + row_y**2).min() <= 0:
        _refuse()
    if (column_x * column_x[0, 0] + column_y * column_y[0, 0]).min() <= 0:
        _refuse()
    if (row_x * row_x[0, 0] + row_y * row_y[0, 0]).min() <= 0:
        _refuse()
    cell_area = column_x[:-1, :] * row_y[:, :-1] - column_y[:-1, :] * row_x[:, :-1]
    if not (cell_area > 0).all() and not (cell_area < 0).all():
        _refuse()
    points = [(float(x[0, j]), float(y[0, j])) for j in range(x.shape[1])]
    points.extend((float(x[i, -1]), float(y[i, -1])) for i in range(1, x.shape[0]))
    points.extend(
        (float(x[-1, j]), float(y[-1, j])) for j in range(x.shape[1] - 2, -1, -1)
    )
    points.extend(
        (float(x[i, 0]), float(y[i, 0])) for i in range(x.shape[0] - 2, 0, -1)
    )
    polygon = Polygon(points)
    if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
        _refuse()
    return polygon


def _buffered_box(grid, buffer):
    if type(buffer) not in (int, float) or not math.isfinite(buffer) or buffer < 0:
        _refuse()
    box = grid.bbox(buffer=buffer)
    if len(box) != 4 or any(not math.isfinite(float(v)) for v in box):
        _refuse()
    x0, y0, x1, y1 = (float(v) for v in box)
    if x0 >= x1 or y0 >= y1:
        _refuse()
    return x0, y0, x1, y1


def validate_actual_model(model, reference_model, document, reference):
    """Check exact pinned generated mesh and actual adapter buffer boxes.

    Call only after public pinned Pydantic construction, inside the pure I/O fence.
    """
    expected = document["config"]["cgrid"]["grid"]
    actual, pinned = model.config.grid, reference_model.config.grid
    x, y = actual.x, actual.y
    if x.shape != (expected["my"] + 1, expected["mx"] + 1) or y.shape != x.shape:
        _refuse()
    if x.shape[0] < 2 or x.shape[1] < 2:
        _refuse()
    polygon, pinned_polygon = _polygon(actual), _polygon(pinned)
    if not pinned_polygon.buffer(_EPSILON).covers(polygon):
        _refuse()
    points = document["config"]["output"]["points"]
    from shapely.geometry import Point

    for px, py in zip(points["xp"], points["yp"]):
        if not polygon.buffer(_EPSILON).covers(Point(px, py)):
            _refuse()
    current_sources = [model.config.inpgrid.bottom, *model.config.inpgrid.input]
    pinned_sources = [
        reference_model.config.inpgrid.bottom,
        *reference_model.config.inpgrid.input,
    ]
    if len(current_sources) != len(pinned_sources):
        _refuse()
    for current, base in zip(current_sources, pinned_sources):
        query, baseline = (
            _buffered_box(actual, current.buffer),
            _buffered_box(pinned, base.buffer),
        )
        if any(query[i] < baseline[i] - _EPSILON for i in (0, 1)) or any(
            query[i] > baseline[i] + _EPSILON for i in (2, 3)
        ):
            _refuse()
    return True


def expected_outputs(document, reference, model_json_sha256):
    period = validate(document, reference)
    grid = document["config"]["cgrid"]["grid"]
    points = len(document["config"]["output"]["points"]["xp"])
    return {
        "profile_id": POLICY_ID,
        "profile_version": 1,
        "model_json_sha256": model_json_sha256,
        "netcdf": ["swangrid.nc", "swanspec.nc"],
        "files": ["swantable.txt", f"hotfile_{period['end']:%Y%m%dT%H%M%S}.txt"],
        "dimensions": {
            "swangrid.nc": {
                "time": period["instants"],
                "yc": grid["my"] + 1,
                "xc": grid["mx"] + 1,
            },
            "swanspec.nc": {
                "points": points,
                "time": period["instants"],
                "frequency": 35,
                "direction": 36,
            },
        },
    }
