"""Offline city selection from the attributed GeoNames snapshot."""

import json
from importlib.resources import files

from .models import BirthPlace


def list_cities() -> tuple[BirthPlace, ...]:
    resource = files("destiny_calculator").joinpath("data/cities.json")
    snapshot = json.loads(resource.read_text(encoding="utf-8"))
    return tuple(
        BirthPlace(city["name"], city["latitude"], city["longitude"], city["timezone"])
        for city in snapshot["cities"]
    )


def get_city(name: str) -> BirthPlace:
    for city in list_cities():
        if city.name == name:
            return city
    raise ValueError(f"Unknown built-in city: {name}")
