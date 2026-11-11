"""QA-012 · фикстуры наборов AD на Samba: приложение целиком (как у CORE и ADM) и контроллер."""

from tests.integration.core.conftest import (  # noqa: F401
    api,
    clock,
    encryption_key,
    events,
    world,
)
from tests.support.samba import samba, samba_env  # noqa: F401
