from pathlib import Path

from tea.storage import FileTokenStore, MemoryTokenStore, TokenBundle


def test_memory_token_store_roundtrip():
    store = MemoryTokenStore()
    store.save(TokenBundle(access_token="a", refresh_token="b", expires_at=42.0))
    bundle = store.load()
    assert bundle.access_token == "a"
    assert bundle.refresh_token == "b"
    assert bundle.expires_at == 42.0


def test_file_token_store_roundtrip(tmp_path: Path):
    path = tmp_path / "token.json"
    store = FileTokenStore(path)
    bundle = TokenBundle(access_token="token", refresh_token="refresh", expires_at=123.4)
    store.save(bundle)
    loaded = store.load()
    assert loaded == bundle
