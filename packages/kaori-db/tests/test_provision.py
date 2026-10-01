"""kaori_db.provision refuses unsafe login names and passwords before it touches a database."""
import pytest

from kaori_db.provision import main, provision

ADMIN = "postgresql+psycopg2://kaori_admin:x@/kaori?host=/nowhere"


@pytest.mark.parametrize("runtime", [
    "postgresql+psycopg2://Kaori-API:0123456789abcdef0123@/kaori",        # not a plain name
    "postgresql+psycopg2://x;drop:0123456789abcdef0123@/kaori",           # injection attempt
    "postgresql+psycopg2://kaori_api_antalya:short@/kaori",               # weak password
    "postgresql+psycopg2://kaori_api_antalya:0123456789abc'def0123@/kaori",  # quote
])
def test_unsafe_runtime_login_is_refused(runtime):
    with pytest.raises(ValueError):
        provision(ADMIN, runtime)


def test_needs_both_urls(monkeypatch):
    monkeypatch.delenv("ADMIN_DATABASE_URL", raising=False)
    monkeypatch.delenv("RUNTIME_DATABASE_URL", raising=False)
    assert main() == 2
