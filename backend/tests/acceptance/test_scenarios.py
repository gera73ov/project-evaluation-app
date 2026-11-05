"""QA-002 · привязка сценариев ``features/*.feature`` (SPEC 17.2) к pytest-bdd.

Определения шагов добавляют задачи QA-012…QA-017 в модули ``steps_*.py`` этого каталога.
"""

from pytest_bdd import scenarios

scenarios("features")
