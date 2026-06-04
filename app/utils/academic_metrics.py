from typing import Dict

def compute_ahs(avg_attendance: float, pass_rate: float, risk_ratio: float, avg_marks: float) -> Dict:
    """
    Compute the Academic Health Score (AHS).
    This is the authoritative formula used across the platform.
    
    Formula:
    AHS = (avg_attendance * 0.30) + (pass_rate * 0.30) + ((1 - risk_ratio) * 100 * 0.25) + (avg_marks * 0.15)
    """
    # Ensure inputs are floats and cap them appropriately
    avg_attendance = float(avg_attendance or 0)
    pass_rate = float(pass_rate or 0)
    risk_ratio = float(risk_ratio or 0)
    avg_marks = float(avg_marks or 0)

    score = round(
        avg_attendance * 0.30 +
        pass_rate * 0.30 +
        ((1 - risk_ratio) * 100) * 0.25 +
        avg_marks * 0.15,
        1
    )
    score = min(100, max(0, score))

    if score >= 85:
        grade, color = "Excellent", "green"
    elif score >= 70:
        grade, color = "Good", "blue"
    elif score >= 55:
        grade, color = "Needs Attention", "amber"
    else:
        grade, color = "Critical", "red"

    return {
        "score": score,
        "grade": grade,
        "color": color,
        "components": {
            "attendance": avg_attendance,
            "pass_rate": pass_rate,
            "risk_ratio": round(risk_ratio * 100, 1),
            "subject_avg": avg_marks,
        }
    }
