import os

from app.core.config import load_env_file


def test_load_env_file_reads_values_without_overwriting_existing_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "QICHACHA_API_KEY=file_key",
                "QICHACHA_API_SECRET=file_secret",
                "AUDIT_STORAGE_DIR=storage_from_file",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("QICHACHA_API_KEY", raising=False)
    monkeypatch.setenv("QICHACHA_API_SECRET", "system_secret")

    values = load_env_file(env_file)

    assert values["QICHACHA_API_KEY"] == "file_key"
    assert os.environ["QICHACHA_API_KEY"] == "file_key"
    assert os.environ["QICHACHA_API_SECRET"] == "system_secret"
