from tea.config import TeaSettings


def test_default_settings():
    settings = TeaSettings()
    assert settings.novnc_enabled is True
    assert settings.novnc_password_enabled is False
    assert settings.dry_run is False
    assert settings.relay_send_enabled is True
    assert settings.relay_query_enabled is False


def test_boolean_properties(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "TEA_NOVNC_ENABLED=false",
                "TEA_DRY_RUN=true",
                "TEA_RELAY_QUERY_ENABLED=true",
            ]
        ),
        encoding="utf-8",
    )
    settings = TeaSettings(_env_file=str(env_path))
    assert settings.novnc_enabled is False
    assert settings.dry_run is True
    assert settings.relay_query_enabled is True
