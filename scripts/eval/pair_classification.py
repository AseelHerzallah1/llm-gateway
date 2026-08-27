"""Answer-reusability classification for cache threshold experiments.

Class A: strongly cache-equivalent — same cached answer should safely satisfy both.
Class B: semantically similar but not guaranteed answer-equivalent.
Class C: misclassified positive — reuse would often be wrong.

Hard negatives and unrelated pairs remain negative categories.
"""

from __future__ import annotations

# Class A — strongly cache-equivalent (14 pairs)
CLASS_A_LABELS: frozenset[str] = frozenset(
    {
        "pos_https_security",
        "pos_python_decorators",
        "pos_france_capital",
        "pos_sql_join",
        "pos_binary_search_complexity",
        "pos_exercise_benefits",
        "pos_gdp",
        "pos_celsius_fahrenheit",
        "pos_speed_of_light",
        "pos_git_merge",
        "pos_seasons",
        "pos_get_vs_post",
        "pos_api",
        "pos_wifi",
    }
)

# Class B — similar intent, not guaranteed answer-equivalent (15 pairs)
CLASS_B_LABELS: frozenset[str] = frozenset(
    {
        "pos_photosynthesis",
        "pos_boil_egg",
        "pos_machine_learning",
        "pos_cover_letter",
        "pos_vaccination",
        "pos_recursion",
        "pos_sleep_quality",
        "pos_blockchain",
        "pos_supply_demand",
        "pos_reduce_stress",
        "pos_car_engine",
        "pos_climate_change",
        "pos_learn_language",
        "pos_oop",
        "pos_pythagorean",
    }
)

# Class C — misclassified as positive (1 pair)
CLASS_C_LABELS: frozenset[str] = frozenset({"pos_inflation"})

# Difficult pairs for side-by-side reporting
DIFFICULT_PAIR_LABELS: tuple[str, ...] = (
    "pos_https_security",
    "pos_france_capital",
    "pos_python_decorators",
    "neg_oauth_auth_vs_authz",
    "neg_list_append_vs_extend",
    "neg_sort_vs_reverse_list",
    "neg_type1_vs_type2_diabetes",
)
