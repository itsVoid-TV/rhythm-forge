"""Persistent stars, color ownership, and equipment for Rhythm Forge."""

from __future__ import annotations

import configparser
from pathlib import Path


COLOR_PRICE = 15

COLOR_GROUPS: dict[str, list[dict[str, str]]] = {
    "spam": [
        {"id": "spamDefault", "name": "Forge Orange", "hex": "#ffb83f", "kind": "default"},
        {"id": "spamBlue", "name": "Pulse Blue", "hex": "#4d9cff", "kind": "shop"},
        {"id": "spamPink", "name": "Hot Pink", "hex": "#ff5fd2", "kind": "shop"},
        {"id": "spamGreen", "name": "Arcade Green", "hex": "#58e38c", "kind": "shop"},
        {"id": "spamPurple", "name": "Nova Purple", "hex": "#aa70ff", "kind": "shop"},
        {"id": "spamWhite", "name": "Starlight White", "hex": "#f4f5fb", "kind": "shop"},
        {"id": "spamRed", "name": "Overdrive Red", "hex": "#ff5c6f", "kind": "shop"},
        {"id": "eventAurora", "name": "Event Aurora", "hex": "#2dffe2", "kind": "event"},
    ],
    "hold": [
        {"id": "holdDefault", "name": "Mint Hold", "hex": "#70edc2", "kind": "default"},
        {"id": "holdRed", "name": "Signal Red", "hex": "#ff526f", "kind": "shop"},
        {"id": "holdGold", "name": "Gold Hold", "hex": "#ffc857", "kind": "shop"},
        {"id": "holdBlue", "name": "Deep Blue", "hex": "#4d9cff", "kind": "shop"},
        {"id": "holdPurple", "name": "Royal Purple", "hex": "#b477ff", "kind": "shop"},
        {"id": "holdWhite", "name": "Pure White", "hex": "#f4f5fb", "kind": "shop"},
        {"id": "holdOrange", "name": "Sunset Orange", "hex": "#ff9d45", "kind": "shop"},
        {"id": "eventCrimson", "name": "Event Crimson", "hex": "#ff315f", "kind": "event"},
    ],
    "lane": [
        {"id": "laneDefault", "name": "Forge Violet", "hex": "#8a70ff", "kind": "default"},
        {"id": "laneYellow", "name": "Beat Yellow", "hex": "#ffe14d", "kind": "shop"},
        {"id": "laneIce", "name": "Ice Line", "hex": "#62d9ff", "kind": "shop"},
        {"id": "laneGreen", "name": "Laser Green", "hex": "#5ee6a8", "kind": "shop"},
        {"id": "laneRed", "name": "Warning Red", "hex": "#ff5a70", "kind": "shop"},
        {"id": "laneWhite", "name": "Clean White", "hex": "#f4f5fb", "kind": "shop"},
        {"id": "lanePink", "name": "Candy Pink", "hex": "#ff70c8", "kind": "shop"},
        {"id": "eventSolar", "name": "Event Solar", "hex": "#ff9d2d", "kind": "event"},
    ],
}

PROGRESSION_DEFAULTS = {
    "stars": "0",
    "lifetimeStars": "0",
    "songsCompleted": "0",
    "eventWins": "0",
    "ownedSpam": "|spamDefault|",
    "ownedHold": "|holdDefault|",
    "ownedLane": "|laneDefault|",
    "equippedSpam": "spamDefault",
    "equippedHold": "holdDefault",
    "equippedLane": "laneDefault",
}


def advancement_rank(lifetime_stars: int) -> str:
    if lifetime_stars >= 100:
        return "RHYTHM LEGEND"
    if lifetime_stars >= 60:
        return "STAR MASTER"
    if lifetime_stars >= 30:
        return "BEAT RIDER"
    if lifetime_stars >= 10:
        return "RISING PLAYER"
    return "ROOKIE"


class ProgressionStore:
    """Read and update the same INI section used by QML Settings."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _parser() -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        return parser

    def read(self) -> dict[str, str]:
        parser = self._parser()
        parser.read(self.path, encoding="utf-8")
        values = dict(PROGRESSION_DEFAULTS)
        if parser.has_section("progression"):
            values.update(dict(parser.items("progression")))
        return values

    def write(self, values: dict[str, str]) -> None:
        parser = self._parser()
        parser.read(self.path, encoding="utf-8")
        if not parser.has_section("progression"):
            parser.add_section("progression")
        for key in PROGRESSION_DEFAULTS:
            parser.set("progression", key, str(values.get(key, PROGRESSION_DEFAULTS[key])))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".ini.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            parser.write(stream, space_around_delimiters=False)
        temporary.replace(self.path)

    @staticmethod
    def _owned_key(category: str) -> str:
        return {"spam": "ownedSpam", "hold": "ownedHold", "lane": "ownedLane"}[category]

    @staticmethod
    def _equipped_key(category: str) -> str:
        return {"spam": "equippedSpam", "hold": "equippedHold", "lane": "equippedLane"}[category]

    def is_owned(self, values: dict[str, str], category: str, color_id: str) -> bool:
        return f"|{color_id}|" in values[self._owned_key(category)]

    def buy(self, category: str, color_id: str, price: int = COLOR_PRICE) -> tuple[bool, str]:
        values = self.read()
        if self.is_owned(values, category, color_id):
            return False, "Color already owned."
        stars = int(values["stars"])
        if stars < price:
            return False, f"You need {price - stars} more stars."
        values["stars"] = str(stars - price)
        key = self._owned_key(category)
        values[key] += f"{color_id}|"
        self.write(values)
        return True, "Color unlocked. Open Inventory to equip it."

    def equip(self, category: str, color_id: str) -> tuple[bool, str]:
        values = self.read()
        if not self.is_owned(values, category, color_id):
            return False, "Unlock this color before equipping it."
        values[self._equipped_key(category)] = color_id
        self.write(values)
        return True, "Color equipped."
