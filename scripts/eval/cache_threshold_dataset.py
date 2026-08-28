"""Evaluation dataset for semantic cache threshold experiments.

Each pair is labeled by expected cache equivalence under ideal semantic matching:
- positive: same intent, different phrasing (should hit at a useful threshold)
- hard_negative: overlapping topic/vocabulary, different intent (must miss)
- unrelated: easy negative sanity check (must miss)

Not used in production routing — experimental evaluation only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalPair:
    label: str
    prompt_a: str
    prompt_b: str
    category: str  # positive | hard_negative | unrelated


EVAL_PAIRS: tuple[EvalPair, ...] = (
    # --- 30 positive semantic pairs (same intent, different phrasing) ---
    EvalPair(
        "pos_https_security",
        "Why is HTTPS safer than HTTP?",
        "What makes HTTPS more secure than HTTP?",
        "positive",
    ),
    EvalPair(
        "pos_python_decorators",
        "Explain what a Python decorator does.",
        "What is the purpose of decorators in Python?",
        "positive",
    ),
    EvalPair(
        "pos_france_capital",
        "What is the capital of France?",
        "Which city serves as France's capital?",
        "positive",
    ),
    EvalPair(
        "pos_photosynthesis",
        "How does photosynthesis work in plants?",
        "Explain the process of photosynthesis in plants.",
        "positive",
    ),
    EvalPair(
        "pos_boil_egg",
        "What is the best way to boil an egg?",
        "How do I hard-boil an egg properly?",
        "positive",
    ),
    EvalPair(
        "pos_machine_learning",
        "What is machine learning?",
        "Can you define machine learning in simple terms?",
        "positive",
    ),
    EvalPair(
        "pos_sql_join",
        "What does a SQL JOIN do?",
        "Explain how JOINs work in SQL.",
        "positive",
    ),
    EvalPair(
        "pos_binary_search_complexity",
        "What is the time complexity of binary search?",
        "How fast is binary search in big-O terms?",
        "positive",
    ),
    EvalPair(
        "pos_cover_letter",
        "How should I write a strong cover letter?",
        "What makes an effective cover letter?",
        "positive",
    ),
    EvalPair(
        "pos_exercise_benefits",
        "What are the health benefits of regular exercise?",
        "Why is exercising regularly good for your health?",
        "positive",
    ),
    EvalPair(
        "pos_gdp",
        "What is GDP?",
        "Define gross domestic product.",
        "positive",
    ),
    EvalPair(
        "pos_vaccination",
        "How do vaccines protect against disease?",
        "Why do vaccinations help prevent illness?",
        "positive",
    ),
    EvalPair(
        "pos_recursion",
        "Explain recursion in programming for a beginner.",
        "What is recursion and how does it work in code?",
        "positive",
    ),
    EvalPair(
        "pos_celsius_fahrenheit",
        "How do you convert Celsius to Fahrenheit?",
        "What is the formula to convert from Celsius to Fahrenheit?",
        "positive",
    ),
    EvalPair(
        "pos_speed_of_light",
        "What is the speed of light in a vacuum?",
        "How fast does light travel in empty space?",
        "positive",
    ),
    EvalPair(
        "pos_git_merge",
        "How do I merge one Git branch into another?",
        "What are the steps to merge branches in Git?",
        "positive",
    ),
    EvalPair(
        "pos_seasons",
        "Why do we have seasons on Earth?",
        "What causes seasons to change on Earth?",
        "positive",
    ),
    EvalPair(
        "pos_get_vs_post",
        "What is the difference between HTTP GET and POST?",
        "How do GET and POST requests differ in HTTP?",
        "positive",
    ),
    EvalPair(
        "pos_sleep_quality",
        "How can I improve my sleep quality?",
        "What habits help you sleep better at night?",
        "positive",
    ),
    EvalPair(
        "pos_blockchain",
        "What is a blockchain?",
        "Explain blockchain technology in simple terms.",
        "positive",
    ),
    EvalPair(
        "pos_supply_demand",
        "Explain supply and demand in economics.",
        "What is the law of supply and demand?",
        "positive",
    ),
    EvalPair(
        "pos_reduce_stress",
        "What are effective ways to reduce stress?",
        "How can I manage stress in daily life?",
        "positive",
    ),
    EvalPair(
        "pos_api",
        "What is an API?",
        "Define an application programming interface.",
        "positive",
    ),
    EvalPair(
        "pos_car_engine",
        "How does a car engine work at a basic level?",
        "Explain the basic operation of an internal combustion engine in a car.",
        "positive",
    ),
    EvalPair(
        "pos_climate_change",
        "What is climate change?",
        "Define climate change and why it matters.",
        "positive",
    ),
    EvalPair(
        "pos_learn_language",
        "What is the best way to learn a new language?",
        "How can adults effectively learn a foreign language?",
        "positive",
    ),
    EvalPair(
        "pos_oop",
        "What is object-oriented programming?",
        "Explain object-oriented programming principles.",
        "positive",
    ),
    EvalPair(
        "pos_wifi",
        "How does WiFi work?",
        "Explain how wireless internet connectivity works.",
        "positive",
    ),
    EvalPair(
        "pos_pythagorean",
        "What is the Pythagorean theorem?",
        "State the Pythagorean theorem and what it relates.",
        "positive",
    ),
    EvalPair(
        "pos_inflation",
        "What is inflation in economics?",
        "Define inflation and how it affects prices.",
        "positive",
    ),
    # --- 30 hard-negative pairs (same topic, different intent) ---
    EvalPair(
        "neg_diabetes_symptoms_causes",
        "What are the symptoms of diabetes?",
        "What causes diabetes?",
        "hard_negative",
    ),
    EvalPair(
        "neg_diabetes_symptoms_treatment",
        "What are the symptoms of diabetes?",
        "How is diabetes treated?",
        "hard_negative",
    ),
    EvalPair(
        "neg_http_cache_vs_semantic_cache",
        "How does HTTP caching work?",
        "How does semantic caching for LLM responses work?",
        "hard_negative",
    ),
    EvalPair(
        "neg_sort_vs_reverse_list",
        "How do I sort a Python list?",
        "How do I reverse a Python list?",
        "hard_negative",
    ),
    EvalPair(
        "neg_list_append_vs_extend",
        "What does list.append do in Python?",
        "What does list.extend do in Python?",
        "hard_negative",
    ),
    EvalPair(
        "neg_ml_define_vs_train",
        "What is machine learning?",
        "How do I train a machine learning model from scratch?",
        "hard_negative",
    ),
    EvalPair(
        "neg_git_merge_vs_rebase",
        "How do I merge branches in Git?",
        "When should I use git rebase instead of merge?",
        "hard_negative",
    ),
    EvalPair(
        "neg_inflation_cause_vs_effect",
        "What causes inflation?",
        "How does inflation affect consumers?",
        "hard_negative",
    ),
    EvalPair(
        "neg_running_start_vs_knee_pain",
        "How should a beginner start running?",
        "How do I treat knee pain caused by running?",
        "hard_negative",
    ),
    EvalPair(
        "neg_sql_select_vs_delete",
        "How do I write a SQL SELECT query?",
        "How do I delete rows with SQL?",
        "hard_negative",
    ),
    EvalPair(
        "neg_encryption_define_vs_howto",
        "What is encryption?",
        "How do I encrypt a file on my laptop?",
        "hard_negative",
    ),
    EvalPair(
        "neg_heart_attack_symptoms_vs_first_aid",
        "What are the symptoms of a heart attack?",
        "What first aid should I give during a heart attack?",
        "hard_negative",
    ),
    EvalPair(
        "neg_resume_vs_salary",
        "How do I write a resume?",
        "How do I negotiate a higher salary?",
        "hard_negative",
    ),
    EvalPair(
        "neg_climate_causes_vs_solutions",
        "What causes climate change?",
        "What are practical solutions to climate change?",
        "hard_negative",
    ),
    EvalPair(
        "neg_tcp_vs_udp",
        "What is TCP and when is it used?",
        "What is UDP and when is it used?",
        "hard_negative",
    ),
    EvalPair(
        "neg_react_state_vs_props",
        "What is React state used for?",
        "What are props in React used for?",
        "hard_negative",
    ),
    EvalPair(
        "neg_compile_vs_runtime_error",
        "What is a compile-time error?",
        "What is a runtime error?",
        "hard_negative",
    ),
    EvalPair(
        "neg_db_normalization_vs_indexing",
        "What is database normalization?",
        "What is database indexing?",
        "hard_negative",
    ),
    EvalPair(
        "neg_oauth_auth_vs_authz",
        "How does OAuth authentication work?",
        "How does OAuth authorization work?",
        "hard_negative",
    ),
    EvalPair(
        "neg_type1_vs_type2_diabetes",
        "What are symptoms of type 1 diabetes?",
        "What are symptoms of type 2 diabetes?",
        "hard_negative",
    ),
    EvalPair(
        "neg_array_vs_linked_list",
        "What are advantages of arrays?",
        "What are advantages of linked lists?",
        "hard_negative",
    ),
    EvalPair(
        "neg_bake_vs_store_bread",
        "How do I bake sourdough bread?",
        "How should I store bread to keep it fresh?",
        "hard_negative",
    ),
    EvalPair(
        "neg_primary_vs_foreign_key",
        "What is a primary key in SQL?",
        "What is a foreign key in SQL?",
        "hard_negative",
    ),
    EvalPair(
        "neg_depression_symptoms_vs_treatment",
        "What are common symptoms of depression?",
        "What treatments exist for depression?",
        "hard_negative",
    ),
    EvalPair(
        "neg_cpu_vs_gpu",
        "What does a CPU do in a computer?",
        "What does a GPU do in a computer?",
        "hard_negative",
    ),
    EvalPair(
        "neg_import_vs_export_econ",
        "What are imports in international trade?",
        "What are exports in international trade?",
        "hard_negative",
    ),
    EvalPair(
        "neg_http_vs_https",
        "How does HTTP work?",
        "How does HTTPS work?",
        "hard_negative",
    ),
    EvalPair(
        "neg_overfitting_vs_underfitting",
        "What is overfitting in machine learning?",
        "What is underfitting in machine learning?",
        "hard_negative",
    ),
    EvalPair(
        "neg_flu_symptoms_vs_prevention",
        "What are symptoms of the flu?",
        "How can I prevent catching the flu?",
        "hard_negative",
    ),
    EvalPair(
        "neg_rest_vs_graphql",
        "What is a REST API?",
        "What is GraphQL?",
        "hard_negative",
    ),
    # --- 10 unrelated pairs ---
    EvalPair(
        "unrel_france_bread",
        "What is the capital of France?",
        "How do I bake sourdough bread?",
        "unrelated",
    ),
    EvalPair(
        "unrel_python_weather",
        "How do I sort a Python list?",
        "What is the weather like in Tokyo?",
        "unrelated",
    ),
    EvalPair(
        "unrel_diabetes_car",
        "What are the symptoms of diabetes?",
        "How often should I change my car's oil?",
        "unrelated",
    ),
    EvalPair(
        "unrel_ml_pasta",
        "What is machine learning?",
        "Give me a simple pasta recipe.",
        "unrelated",
    ),
    EvalPair(
        "unrel_git_piano",
        "How do I merge branches in Git?",
        "How do I play a C major chord on piano?",
        "unrelated",
    ),
    EvalPair(
        "unrel_sql_football",
        "How do I write a SQL SELECT query?",
        "What are the basic rules of football?",
        "unrelated",
    ),
    EvalPair(
        "unrel_photosynthesis_stocks",
        "How does photosynthesis work in plants?",
        "How does the stock market work?",
        "unrelated",
    ),
    EvalPair(
        "unrel_sleep_rome",
        "How can I improve my sleep quality?",
        "Who were the main rulers of ancient Rome?",
        "unrelated",
    ),
    EvalPair(
        "unrel_blockchain_garden",
        "What is a blockchain?",
        "How do I start a vegetable garden?",
        "unrelated",
    ),
    EvalPair(
        "unrel_wifi_marine",
        "How does WiFi work?",
        "What is coral bleaching in marine biology?",
        "unrelated",
    ),
)

THRESHOLDS: tuple[float, ...] = (0.70, 0.75, 0.80, 0.82, 0.85, 0.88, 0.90, 0.92)

BORDERLINE_THRESHOLDS: tuple[float, ...] = (0.80, 0.82, 0.85, 0.88, 0.90, 0.92)
