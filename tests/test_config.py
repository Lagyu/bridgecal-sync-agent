from __future__ import annotations

from pathlib import Path

from bridgecal.config import load_config


def test_load_config_accepts_utf8_bom(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    config_text = 'data_dir = "C:/BridgeCal"\n\n[google]\ncalendar_id = "primary"\n'
    cfg_path.write_bytes(b"\xef\xbb\xbf" + config_text.encode("utf-8"))

    config = load_config(cfg_path)

    assert config.google.calendar_id == "primary"
    assert config.google.client_secret_path == config.data_dir / "google_client_secret.json"
    assert config.google.insecure_tls_skip_verify is True


def test_load_config_parses_insecure_tls_skip_verify(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    config_text = (
        'data_dir = "C:/BridgeCal"\n'
        "\n"
        "[google]\n"
        'calendar_id = "primary"\n'
        "insecure_tls_skip_verify = false\n"
    )
    cfg_path.write_text(config_text, encoding="utf-8")

    config = load_config(cfg_path)

    assert config.google.insecure_tls_skip_verify is False
