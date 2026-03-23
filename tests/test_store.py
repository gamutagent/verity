import pytest
import json
import sqlite3

def test_local_json_save(temp_dir):
    json_path = temp_dir / "store.json"
    data = {"id": "hash123", "title": "Test"}
    
    with open(json_path, 'w') as f:
        json.dump([data], f)
        
    with open(json_path, 'r') as f:
        loaded = json.load(f)
        assert loaded[0]["id"] == "hash123"

def test_sqlite_save(temp_dir):
    db_path = temp_dir / "store.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO items (id, title) VALUES (?, ?)", ("hash123", "Test"))
    conn.commit()
    
    cur = conn.execute("SELECT title FROM items WHERE id=?", ("hash123",))
    assert cur.fetchone()[0] == "Test"
    conn.close()

def test_deduplication():
    seen = set()
    url_hash = "abc1234"
    
    assert url_hash not in seen
    seen.add(url_hash)
    assert url_hash in seen # Dup detected
