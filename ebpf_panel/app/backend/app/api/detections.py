import json
from fastapi import APIRouter
from app.core.settings import settings
from app.models.schemas import DetectedIpItem, DetectionItem

router = APIRouter()

SEVERITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _read_detection_lines():
    path = settings.resolved_detections_file
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _parse_detection_lines(include_logged_only=False):
    items = []
    for line in _read_detection_lines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("logged_only") and not include_logged_only:
            continue
        items.append(data)
    return items


def _write_detection_lines(lines):
    path = settings.resolved_detections_file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    content = "\n".join(lines)
    if content:
        content += "\n"
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


@router.get("", response_model=list[DetectionItem])
def list_detections():
    items = []
    for data in _parse_detection_lines():
        items.append(
            DetectionItem(
                timestamp=data.get("timestamp"),
                src_ip=data.get("src_ip"),
                type=data.get("type"),
                severity=data.get("severity"),
                score=data.get("score"),
                detail=data.get("detail"),
                raw=data,
            )
        )
    return list(reversed(items[-200:]))


@router.get("/ips", response_model=list[DetectedIpItem])
def list_detected_ips():
    by_ip = {}
    for data in _parse_detection_lines():
        ip = data.get("src_ip")
        if not ip:
            continue

        current = by_ip.setdefault(
            ip,
            {
                "src_ip": ip,
                "count": 0,
                "first_seen": data.get("timestamp"),
                "last_seen": None,
                "max_severity": None,
                "latest_type": None,
                "latest_score": None,
                "latest_detail": None,
                "types": set(),
            },
        )

        severity = data.get("severity")
        if (
            severity
            and SEVERITY_RANK.get(str(severity).lower(), 0)
            > SEVERITY_RANK.get(str(current.get("max_severity") or "").lower(), 0)
        ):
            current["max_severity"] = severity

        attack_type = data.get("type")
        if attack_type:
            current["types"].add(attack_type)

        current["count"] += 1
        current["last_seen"] = data.get("timestamp")
        current["latest_type"] = attack_type
        current["latest_score"] = data.get("score")
        current["latest_detail"] = data.get("detail")

    items = []
    for item in by_ip.values():
        item["types"] = sorted(item["types"])
        items.append(DetectedIpItem(**item))

    return sorted(items, key=lambda item: item.last_seen or "", reverse=True)


@router.delete("")
def clear_detections():
    _write_detection_lines([])
    return {"ok": True}


@router.delete("/ips/{ip}")
def delete_detected_ip(ip):
    kept = []
    removed = 0
    for line in _read_detection_lines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue

        if data.get("src_ip") == ip:
            removed += 1
        else:
            kept.append(line)

    _write_detection_lines(kept)
    return {"ok": True, "removed": removed}
