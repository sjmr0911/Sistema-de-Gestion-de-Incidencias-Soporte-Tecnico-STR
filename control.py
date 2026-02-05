def control_action(severity):
    if severity == 4:
        return "ESCALATE_IMMEDIATELY"
    if severity == 3:
        return "ESCALATE"
    if severity == 2:
        return "AUTO_RESPONSE"
    return "LOG_ONLY"
