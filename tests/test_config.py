from app.config import Settings


def test_comma_separated_trusted_hosts_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUSTED_HOSTS", "example.com,api.example.com")
    settings = Settings(app_data_dir=tmp_path)
    assert settings.trusted_hosts == ["example.com", "api.example.com"]
