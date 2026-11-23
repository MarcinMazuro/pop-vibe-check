"""Scale a recipe to a different number of servings."""

BASE_SERVINGS = 6
INGREDIENTS_KG = {"kurczak": 1.5, "marchew": 0.4, "pietruszka": 0.2}


def scale_recipe(servings: int) -> dict[str, float]:
    """Return ingredient weights for the requested number of servings."""
    factor = servings / BASE_SERVINGS
    return {name: round(kg * factor, 2) for name, kg in INGREDIENTS_KG.items()}


if __name__ == "__main__":
    print(scale_recipe(4))  # dinner for four
