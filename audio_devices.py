"""Choose a real microphone when Windows defaults to playback mixing."""
import re


def preferred_microphone(microphones, default, output_name=""):
    def is_mix(name):
        return any(part in name.casefold() for part in
                   ("立体声混音", "stereo mix", "what u hear", "loopback", "混音"))

    selected = next((item for item in microphones if item["id"] == default), None)
    if selected and not is_mix(selected["name"]):
        return default
    candidates = [item for item in microphones if not is_mix(item["name"])]
    # Windows puts the hardware name in parentheses for both playback and input.
    hardware = re.findall(r"\(([^()]+)\)", output_name)
    if hardware:
        matched = next((item for item in candidates if hardware[-1].casefold() in item["name"].casefold()), None)
        if matched:
            return matched["id"]
    return candidates[0]["id"] if candidates else None
