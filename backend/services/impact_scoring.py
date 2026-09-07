# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Depth-adaptive alarm evaluation and distance-decay pollution scoring.

Port of frontend/src/utils/argoAlarms.ts thresholds to Python,
plus the distance-decay scoring model from the design spec.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field


# ── Depth-adaptive thresholds ────────────────────────────────────────────────

def oxygen_threshold(depth_m: float | None) -> float:
    """Return O₂ alarm threshold (μmol/kg) for the given measurement depth."""
    if depth_m is None or depth_m < 200:
        return 150.0   # surface: well-oxygenated expected
    if depth_m < 1000:
        return 90.0    # OMZ: some depletion natural, <90 is hypoxic
    return 60.0        # abyssal: <60 genuinely concerning


def ph_threshold(depth_m: float | None) -> float:
    """Return pH alarm threshold for the given measurement depth."""
    if depth_m is None or depth_m < 200:
        return 7.95    # surface: normal seawater 8.0–8.3
    if depth_m < 1000:
        return 7.75    # mid-water: naturally lower due to CO₂
    return 7.60        # deep: <7.6 is alarming


THRESHOLDS_DOC = {
    "oxygen_umol_kg": {"surface_lt_200m": 150, "omz_200_1000m": 90, "abyssal_gt_1000m": 60},
    "ph": {"surface_lt_200m": 7.95, "mid_200_1000m": 7.75, "deep_gt_1000m": 7.60},
    "temp_salinity": "anomaly if > 2 standard deviations from dataset mean",
}


# ── Dataset statistics for anomaly detection ─────────────────────────────────

@dataclass
class DatasetStats:
    mean_temp: float | None = None
    std_temp: float | None = None
    mean_sal: float | None = None
    std_sal: float | None = None


def compute_dataset_stats(profiles: list[dict]) -> DatasetStats:
    """Compute mean/std of surface temp and salinity from a list of profile dicts."""
    temps = [p["surface_temp"] for p in profiles if p.get("surface_temp") is not None]
    sals = [p["surface_salinity"] for p in profiles if p.get("surface_salinity") is not None]

    ds = DatasetStats()
    if len(temps) >= 2:
        ds.mean_temp = statistics.mean(temps)
        ds.std_temp = statistics.pstdev(temps) or None
    if len(sals) >= 2:
        ds.mean_sal = statistics.mean(sals)
        ds.std_sal = statistics.pstdev(sals) or None
    return ds


# ── Alarm evaluation ─────────────────────────────────────────────────────────

def evaluate_alarms(profile: dict, stats: DatasetStats) -> tuple[list[str], dict[str, float]]:
    """Return (alarm_keys, alarm_severities) for a single profile.

    Severities are normalized 0–1: abs(threshold - value) / threshold.
    """
    alarms: list[str] = []
    severities: dict[str, float] = {}
    depth = profile.get("depth_m")

    # Oxygen
    o2 = profile.get("oxygen")
    if o2 is not None:
        thresh = oxygen_threshold(depth)
        if o2 < thresh:
            alarms.append("low_oxygen")
            severities["oxygen"] = round(abs(thresh - o2) / thresh, 4)

    # pH
    ph = profile.get("ph")
    if ph is not None:
        thresh = ph_threshold(depth)
        if ph < thresh:
            alarms.append("low_ph")
            severities["ph"] = round(abs(thresh - ph) / thresh, 4)

    # Temp anomaly
    t = profile.get("surface_temp")
    if t is not None and stats.mean_temp is not None and stats.std_temp:
        if abs(t - stats.mean_temp) > 2 * stats.std_temp:
            alarms.append("temp_anomaly")
            severities["temp"] = round(abs(t - stats.mean_temp) / (2 * stats.std_temp), 4)

    # Salinity anomaly
    s = profile.get("surface_salinity")
    if s is not None and stats.mean_sal is not None and stats.std_sal:
        if abs(s - stats.mean_sal) > 2 * stats.std_sal:
            alarms.append("salinity_anomaly")
            severities["salinity"] = round(abs(s - stats.mean_sal) / (2 * stats.std_sal), 4)

    return alarms, severities


# ── Distance-decay scoring ───────────────────────────────────────────────────

@dataclass
class ClaimScore:
    isa_id: str
    contractor_name: str
    resource_type: str | None
    pollution_score: float = 0.0
    alarmed_readings: int = 0
    total_readings_nearby: int = 0
    distance_sum: float = 0.0
    worst_alarm: dict | None = None
    plume_hits: int = 0
    first_seen: str | None = None
    last_seen: str | None = None

    @property
    def avg_distance_km(self) -> float:
        if self.total_readings_nearby == 0:
            return 0.0
        return round(self.distance_sum / self.total_readings_nearby, 1)

    @property
    def time_in_zone_hours(self) -> float:
        if not self.first_seen or not self.last_seen:
            return 0.0
        from datetime import datetime
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        try:
            delta = datetime.strptime(self.last_seen, fmt) - datetime.strptime(self.first_seen, fmt)
            return round(delta.total_seconds() / 3600, 1)
        except ValueError:
            return 0.0


def compute_claim_scores(profiles: list[dict], stats: DatasetStats) -> list[dict]:
    """Compute distance-decay pollution scores per claim.

    Each profile must have: nearest_claim_id, nearest_claim_name, resource_type,
    distance_to_claim_km, date, and sensor fields.

    Returns sorted list of claim score dicts (highest score first).
    """
    claims: dict[str, ClaimScore] = {}

    for p in profiles:
        claim_id = p.get("nearest_claim_id")
        if not claim_id:
            continue

        dist = p.get("distance_to_claim_km")
        if dist is None or dist <= 0:
            dist = 0.1  # floor to avoid division by zero

        if claim_id not in claims:
            claims[claim_id] = ClaimScore(
                isa_id=claim_id,
                contractor_name=p.get("nearest_claim_name", "Unknown"),
                resource_type=p.get("resource_type"),
            )

        cs = claims[claim_id]
        cs.total_readings_nearby += 1
        cs.distance_sum += dist

        date_str = p.get("date", "")
        if cs.first_seen is None or date_str < cs.first_seen:
            cs.first_seen = date_str
        if cs.last_seen is None or date_str > cs.last_seen:
            cs.last_seen = date_str

        alarms, severities = evaluate_alarms(p, stats)
        if alarms:
            cs.alarmed_readings += 1
            for alarm_key, severity in severities.items():
                contribution = severity / dist
                cs.pollution_score += contribution

                # Track worst alarm
                if cs.worst_alarm is None or contribution > cs.worst_alarm.get("_contribution", 0):
                    thresh_map = {"oxygen": oxygen_threshold(p.get("depth_m")),
                                  "ph": ph_threshold(p.get("depth_m")),
                                  "temp": None, "salinity": None}
                    cs.worst_alarm = {
                        "type": alarm_key,
                        "value": p.get({"oxygen": "oxygen", "ph": "ph",
                                        "temp": "surface_temp", "salinity": "surface_salinity"}.get(alarm_key, alarm_key)),
                        "threshold": thresh_map.get(alarm_key),
                        "distance_km": dist,
                        "_contribution": contribution,
                    }

    # Sort by score descending, assign ranks
    result = []
    for rank, cs in enumerate(sorted(claims.values(), key=lambda c: c.pollution_score, reverse=True), 1):
        worst = cs.worst_alarm
        if worst:
            worst.pop("_contribution", None)
        result.append({
            "isa_id": cs.isa_id,
            "contractor_name": cs.contractor_name,
            "resource_type": cs.resource_type,
            "pollution_score": round(cs.pollution_score, 2),
            "rank": rank,
            "alarmed_readings": cs.alarmed_readings,
            "total_readings_nearby": cs.total_readings_nearby,
            "avg_distance_km": cs.avg_distance_km,
            "worst_alarm": worst,
            "plume_hits": cs.plume_hits,
            "time_in_zone_hours": cs.time_in_zone_hours,
        })

    return result


# ── Trail distance calculation ───────────────────────────────────────────────

def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance between two points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def total_trail_distance(profiles: list[dict]) -> float:
    """Sum of great-circle distances between consecutive profile positions."""
    total = 0.0
    for i in range(1, len(profiles)):
        total += haversine_km(
            profiles[i - 1]["lon"], profiles[i - 1]["lat"],
            profiles[i]["lon"], profiles[i]["lat"],
        )
    return round(total, 1)


# ── Findings generation engine ──────────────────────────────────────────────

SEVERITY_RANK: dict[str, int] = {
    "Critical": 0,
    "High": 1,
    "Moderate": 2,
    "Low": 3,
}


def classify_severity(
    alarm_type: str,
    distance_km: float,
    endangered_count: int = 0,
) -> str:
    """Return severity string based on alarm proximity and biodiversity context.

    Rules:
    - Critical: alarm + distance < 25 km + endangered species present
    - High: alarm + distance < 50 km, OR plume origin inside claim
    - Moderate: alarm + distance < 100 km
    - Low: distance >= 100 km
    """
    if distance_km < 25 and endangered_count > 0:
        return "Critical"
    if distance_km < 50:
        return "High"
    if distance_km < 100:
        return "Moderate"
    return "Low"


# ── Internal helpers ─────────────────────────────────────────────────────────

def _alarm_label(alarm_type: str) -> str:
    """Human-readable label for an alarm type key."""
    return {
        "low_oxygen": "Dissolved oxygen",
        "low_ph": "pH",
        "temp_anomaly": "Temperature anomaly",
        "salinity_anomaly": "Salinity anomaly",
    }.get(alarm_type, alarm_type)


def _alarm_unit(alarm_type: str) -> str:
    """Measurement unit string for an alarm type."""
    return {
        "low_oxygen": "μmol/kg",
        "low_ph": "",
        "temp_anomaly": "°C",
        "salinity_anomaly": "PSU",
    }.get(alarm_type, "")


def _alarm_value_key(alarm_type: str) -> str:
    """Profile dict key that holds the measured value for this alarm type."""
    return {
        "low_oxygen": "oxygen",
        "low_ph": "ph",
        "temp_anomaly": "surface_temp",
        "salinity_anomaly": "surface_salinity",
    }.get(alarm_type, alarm_type)


# ── Finding generators ───────────────────────────────────────────────────────

def generate_alarm_finding(
    number: int,
    alarm_type: str,
    profile: dict,
    stats: DatasetStats,
    claim: dict,
    env_context: dict,
) -> dict:
    """Generate a structured finding dict for a sensor alarm.

    Parameters
    ----------
    number : sequential finding number
    alarm_type : one of low_oxygen, low_ph, temp_anomaly, salinity_anomaly
    profile : the Argo profile dict with sensor readings
    stats : DatasetStats for anomaly context
    claim : dict with at least ``isa_id``, ``contractor_name``, ``distance_km``
    env_context : dict with ``vent_count``, ``species_count``, ``endangered_count``,
                  ``seamount_count``
    """
    value_key = _alarm_value_key(alarm_type)
    value = profile.get(value_key)
    depth = profile.get("depth_m")
    distance_km = claim.get("distance_km", 999)
    label = _alarm_label(alarm_type)
    unit = _alarm_unit(alarm_type)
    endangered_count = env_context.get("endangered_count", 0)

    severity = classify_severity(alarm_type, distance_km, endangered_count)

    # Build structured finding fields
    claim_id = claim.get("isa_id", "Unknown")
    contractor = claim.get("contractor_name", "Unknown")

    if alarm_type in ("low_oxygen", "low_ph"):
        if alarm_type == "low_oxygen":
            threshold = oxygen_threshold(depth)
            thresh_name = "abyssal" if (depth or 0) >= 1000 else ("OMZ" if (depth or 0) >= 200 else "surface")
        else:
            threshold = ph_threshold(depth)
            thresh_name = "deep" if (depth or 0) >= 1000 else ("mid-water" if (depth or 0) >= 200 else "surface")
        pct_below = round(abs(threshold - (value or 0)) / threshold * 100, 1) if threshold else 0
        unit_str = f" {unit}" if unit else ""
        observation = (
            f"{label} of {value}{unit_str} recorded at {depth or 'unknown'}m depth, "
            f"{pct_below}% below the {thresh_name} threshold of {threshold}{unit_str}."
        )
        threshold_detail = f"{thresh_name} threshold: {threshold}{unit_str}"
    else:
        if alarm_type == "temp_anomaly" and stats.mean_temp is not None and stats.std_temp:
            mean_val, std_val = stats.mean_temp, stats.std_temp
        elif alarm_type == "salinity_anomaly" and stats.mean_sal is not None and stats.std_sal:
            mean_val, std_val = stats.mean_sal, stats.std_sal
        else:
            mean_val, std_val = None, None
        std_devs = round(abs((value or 0) - mean_val) / std_val, 1) if mean_val is not None and std_val else 0
        unit_str = f" {unit}" if unit else ""
        observation = (
            f"{label} of {value}{unit_str} deviates {std_devs} standard deviations "
            f"from the dataset mean ({round(mean_val, 2) if mean_val else '?'}{unit_str})."
        )
        threshold_detail = f">2σ from dataset mean ({round(mean_val, 2) if mean_val else '?'} ± {round(std_val, 2) if std_val else '?'}{unit_str})"

    spatial_link = f"Recorded {distance_km:.1f} km from concession {claim_id} ({contractor})."

    env_parts = []
    vent_count = env_context.get("vent_count", 0)
    seamount_count = env_context.get("seamount_count", 0)
    species_count = env_context.get("species_count", 0)
    if vent_count > 0:
        env_parts.append(f"{vent_count} hydrothermal vent{'s' if vent_count != 1 else ''} within 50 km")
    if seamount_count > 0:
        env_parts.append(f"{seamount_count} seamount{'s' if seamount_count != 1 else ''} within 10 km")
    if species_count > 0:
        end_str = f" ({endangered_count} endangered)" if endangered_count > 0 else ""
        env_parts.append(f"{species_count} observed species{end_str} within 50 km")
    environmental_context = ". ".join(env_parts) + "." if env_parts else "No notable environmental features nearby."

    return {
        "number": number,
        "type": alarm_type,
        "severity": severity,
        "observation": observation,
        "threshold_detail": threshold_detail,
        "spatial_link": spatial_link,
        "environmental_context": environmental_context,
        "refs": {
            "profile_id": profile.get("profile_id", ""),
            "claim_id": claim_id,
        },
    }


def generate_plume_finding(
    number: int,
    plume: dict,
    profile: dict,
    claim: dict,
    hours: float,
) -> dict:
    """Generate a structured finding for plume backtrack attribution.

    Parameters
    ----------
    number : sequential finding number
    plume : dict with ``origin_lon``, ``origin_lat``, ``speed_km_h``,
            ``distance_to_claim_km``
    profile : the Argo profile associated with this plume trace
    claim : dict with ``isa_id``, ``contractor_name``
    hours : how many hours the plume was backtracked
    """
    origin = plume.get("backtrack_origin", [0, 0])
    dist = plume.get("distance_to_source_km") or 999
    speed = plume.get("speed_cms", 0)
    claim_id = claim.get("isa_id", "Unknown") if claim else plume.get("source_claim_id", "Unknown")
    contractor = claim.get("contractor_name", "Unknown") if claim else plume.get("source_claim_name", "Unknown")

    severity = "High" if dist < 50 else "Moderate"

    observation = (
        f"Particle backtracking over {hours} hours using RK4-integrated CMEMS current data "
        f"traces the water mass at profile {profile.get('profile_id', '?')} to coordinates "
        f"[{origin[0]}, {origin[1]}]."
    )
    spatial_link = (
        f"Origin located {dist} km from concession {claim_id} ({contractor}). "
        f"Current speed at origin: {speed} cm/s."
    )

    return {
        "number": number,
        "type": "plume_attribution",
        "severity": severity,
        "observation": observation,
        "threshold_detail": f"RK4 integration, {hours}h backtrack",
        "spatial_link": spatial_link,
        "environmental_context": "",
        "refs": {
            "profile_id": profile.get("profile_id", ""),
            "claim_id": claim_id,
        },
    }


# ── Risk rating ──────────────────────────────────────────────────────────────

def compute_risk_rating(findings: list[dict]) -> str:
    """Compute overall report risk rating from a list of findings.

    - Critical: any Critical finding OR >= 2 High findings
    - High: any High finding
    - Moderate: any Moderate finding
    - Low: otherwise
    """
    severity_counts: dict[str, int] = {}
    for f in findings:
        sev = f.get("severity", "Low")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    if severity_counts.get("Critical", 0) > 0:
        return "Critical"
    if severity_counts.get("High", 0) >= 2:
        return "Critical"
    if severity_counts.get("High", 0) >= 1:
        return "High"
    if severity_counts.get("Moderate", 0) > 0:
        return "Moderate"
    return "Low"


# ── Narrative generation ─────────────────────────────────────────────────────

def generate_executive_narrative(
    platform_id: str,
    profiles: list[dict],
    findings: list[dict],
    claim_dossiers: list[dict],
    total_distance_km: float,
) -> str:
    """Auto-generate an executive summary paragraph for the evidence report.

    Parameters
    ----------
    platform_id : Argo float WMO identifier
    profiles : list of profile dicts (used for date range)
    findings : list of finding dicts
    claim_dossiers : list of claim score dicts (from compute_claim_scores)
    total_distance_km : total drift distance of the float
    """
    # Date range
    dates = sorted(p.get("date", "") for p in profiles if p.get("date"))
    if dates:
        date_from = dates[0][:10]
        date_to = dates[-1][:10]
        date_range = f"{date_from} to {date_to}"
    else:
        date_range = "unknown period"

    alarm_count = sum(1 for f in findings if f.get("type") != "plume_attribution")
    plume_count = sum(1 for f in findings if f.get("type") == "plume_attribution")

    # Claims implicated
    claim_ids = list(dict.fromkeys(f.get("claim_id") for f in findings if f.get("claim_id")))
    claims_implicated = len(claim_ids)

    # Top claim by risk score
    top_claim = ""
    if claim_dossiers:
        top = claim_dossiers[0]
        claim_info = top.get("claim", top)  # support both dossier and flat format
        top_claim = (
            f" The most significant evidence concerns concession "
            f"{claim_info.get('isa_id', '?')} ({claim_info.get('contractor_name', '?')}), "
            f"with a risk score of {top.get('risk_score', {}).get('total', 0):.2f}."
        )

    parts = [
        f"Argo float {platform_id} drifted {total_distance_km:.1f} km over the period {date_range}, "
        f"recording {len(profiles)} profiles.",
    ]

    if alarm_count or plume_count:
        finding_parts = []
        if alarm_count:
            finding_parts.append(f"{alarm_count} sensor alarm{'s' if alarm_count != 1 else ''}")
        if plume_count:
            finding_parts.append(f"{plume_count} plume backtrack{'s' if plume_count != 1 else ''}")
        parts.append(
            f" Analysis identified {' and '.join(finding_parts)}, "
            f"implicating {claims_implicated} mining claim{'s' if claims_implicated != 1 else ''}."
        )
    else:
        parts.append(" No significant findings were identified during this period.")

    if top_claim:
        parts.append(top_claim)

    return "".join(parts)


def generate_evidence_summary(
    findings: list[dict],
    risk_rating: str,
) -> dict:
    """Generate extractable evidence summary section.

    Returns a dict with ``narrative``, ``finding_counts``, and
    ``recommended_actions``.
    """
    # Count by severity
    counts: dict[str, int] = {"Critical": 0, "High": 0, "Moderate": 0, "Low": 0}
    for f in findings:
        sev = f.get("severity", "Low")
        if sev in counts:
            counts[sev] += 1

    total = len(findings)
    narrative = (
        f"This report contains {total} finding{'s' if total != 1 else ''} "
        f"with an overall risk rating of {risk_rating}. "
        f"Breakdown: {counts['Critical']} critical, {counts['High']} high, "
        f"{counts['Moderate']} moderate, {counts['Low']} low."
    )

    # Recommended actions based on risk rating
    actions: list[str] = []
    if risk_rating == "Critical":
        actions.append("Immediate review of implicated mining operations recommended.")
        actions.append("Notify ISA compliance division with attached evidence.")
        actions.append("Cross-reference with additional Argo floats in the region.")
    elif risk_rating == "High":
        actions.append("Elevated monitoring of implicated claim areas recommended.")
        actions.append("Request additional sensor deployment near flagged concessions.")
    elif risk_rating == "Moderate":
        actions.append("Continue routine monitoring with increased attention to flagged areas.")
    else:
        actions.append("No immediate action required. Continue standard monitoring.")

    return {
        "narrative": narrative,
        "finding_counts": counts,
        "recommended_actions": actions,
    }


def generate_claim_narrative(
    isa_id: str,
    contractor_name: str,
    resource_type: str | None,
    area_km2: float | None,
    vents: list[dict],
    seamounts: list[dict],
    species_count: int,
    endangered_count: int,
    cr_en_count: int = 0,
    nearby_floats: int = 0,
    alarm_count: int = 0,
    plume_count: int = 0,
    risk_rating: str = "Low",
) -> str:
    """Auto-generate executive summary for a claim impact report."""
    area_str = f"{area_km2:,.0f} km²" if area_km2 else "unknown area"
    resource_str = resource_type or "unspecified resources"

    parts = [
        f"Mining concession {isa_id} ({contractor_name}) covers {area_str} "
        f"targeting {resource_str}.",
    ]

    env_parts = []
    if vents:
        active = sum(1 for v in vents if v.get("status") == "Active")
        env_parts.append(
            f"{len(vents)} hydrothermal vent{'s' if len(vents) != 1 else ''} "
            f"({active} active) within 50 km"
        )
    if seamounts:
        env_parts.append(f"{len(seamounts)} seamount{'s' if len(seamounts) != 1 else ''} within 10 km")
    if species_count:
        if cr_en_count > 0:
            env_parts.append(
                f"{species_count} documented species "
                f"({cr_en_count} Critically Endangered/Endangered, "
                f"{endangered_count - cr_en_count} Vulnerable)"
            )
        elif endangered_count:
            env_parts.append(
                f"{species_count} documented species ({endangered_count} Vulnerable)"
            )
        else:
            env_parts.append(f"{species_count} documented species")
    if env_parts:
        parts.append(f" Environmental context includes {', '.join(env_parts)}.")

    if nearby_floats:
        finding_parts = []
        if alarm_count:
            finding_parts.append(f"{alarm_count} sensor alarm{'s' if alarm_count != 1 else ''}")
        if plume_count:
            finding_parts.append(f"{plume_count} plume attribution{'s' if plume_count != 1 else ''}")
        parts.append(
            f" Monitoring from {nearby_floats} Argo float{'s' if nearby_floats != 1 else ''} "
            f"identified {' and '.join(finding_parts) if finding_parts else 'no significant anomalies'}."
        )
    else:
        parts.append(" No Argo float monitoring data is available near this concession.")

    return "".join(parts)


def generate_claim_env_finding(
    number: int,
    finding_type: str,
    isa_id: str,
    contractor_name: str,
    details: dict,
) -> dict:
    """Generate environmental context findings for claim reports."""
    templates = {
        "vent_proximity": {
            "observation": (
                f"{details.get('count', 0)} hydrothermal vent(s) located within 50 km of concession {isa_id}. "
                f"{details.get('active_count', 0)} are classified as active, hosting unique chemosynthetic ecosystems."
            ),
            "severity": "Critical" if details.get("active_count", 0) > 0 else "Moderate",
            "threshold_detail": "ISA Environmental Management Plan requires 50 km buffer from active vents.",
            "environmental_context": (
                "Active hydrothermal vents support endemic species found nowhere else on Earth. "
                "Mining sediment plumes can smother vent communities within hours."
            ),
        },
        "species_risk": {
            "observation": (
                f"{details.get('endangered_count', 0)} IUCN-threatened species "
                f"({details.get('cr_en_count', 0)} CR/EN, "
                f"{details.get('endangered_count', 0) - details.get('cr_en_count', 0)} VU) "
                f"documented within 50 km of {isa_id} "
                f"({details.get('total_count', 0)} species total across {details.get('records', 0)} OBIS records)."
            ),
            "severity": "Critical" if details.get("cr_en_count", 0) > 0 else "High" if details.get("endangered_count", 0) > 2 else "Moderate" if details.get("endangered_count", 0) > 0 else "Low",
            "threshold_detail": "IUCN Red List species (CR/EN/VU) require heightened protection under ISA guidelines.",
            "environmental_context": (
                "Deep-sea species have extremely slow recovery rates. "
                "Population disruption may be irreversible on human timescales."
            ),
        },
        "seamount_overlap": {
            "observation": (
                f"{details.get('count', 0)} seamount(s) within 10 km of concession {isa_id}. "
                "Seamounts serve as biodiversity hotspots and stepping stones for larval dispersal."
            ),
            "severity": "Moderate",
            "threshold_detail": "Seamounts within mining zones face direct habitat destruction risk.",
            "environmental_context": (
                "Seamounts concentrate deep-sea biodiversity and support commercially important species. "
                "Physical removal during mining is permanent."
            ),
        },
    }

    tmpl = templates.get(finding_type, {})
    return {
        "number": number,
        "type": finding_type,
        "severity": tmpl.get("severity", "Low"),
        "observation": tmpl.get("observation", ""),
        "threshold_detail": tmpl.get("threshold_detail", ""),
        "spatial_link": f"Concession {isa_id} ({contractor_name})",
        "environmental_context": tmpl.get("environmental_context", ""),
        "refs": {"claim_id": isa_id},
    }