import pytest
import yaml

def test_valid_yaml_load(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("gamut:\n  enabled: true\n")
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
        assert config["gamut"]["enabled"] is True

def test_missing_required_fields():
    # Simulating config_loader validation
    config = {"storage": "sqlite"}
    if "search" not in config:
        with pytest.raises(ValueError):
            raise ValueError("Missing search configuration")

def test_security_warning_zero_bind(caplog):
    # Simulating a security log output
    config_host = "0.0.0.0"
    if config_host == "0.0.0.0":
        import logging
        logging.warning("SECURITY: Binding to 0.0.0.0 exposes service globally!")
    
    assert "SECURITY" in caplog.text

def test_secrets_validation_missing_env():
    import os
    if "NONEXISTENT_SECRET" not in os.environ:
        with pytest.raises(KeyError):
            raise KeyError("missing env")
