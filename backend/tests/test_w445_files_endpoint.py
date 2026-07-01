"""W4-45: /api/files/serve 端点测试"""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_serve_html_file(client, tmp_path):
    """HTML 文件应正确 serve, Content-Type=text/html"""
    p = tmp_path / "hello.html"
    p.write_text("<!DOCTYPE html><html><body><h1>路明非</h1></body></html>", encoding="utf-8")

    r = client.get(f"/api/files/serve", params={"path": str(p)})
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "路明非" in r.text


def test_serve_bare_filename(client, tmp_path, monkeypatch):
    """bare filename 解析到 backend cwd"""
    # 测试我们能 resolve 路径; 实际 cwd 不一定能写, 用绝对路径 + 改 backend cwd
    import os
    p = tmp_path / "abc.py"
    p.write_text("print('hi')", encoding="utf-8")

    # 临时改 backend cwd 引用 — 通过 _BACKEND_CWD 重绑
    from app.api import files
    monkeypatch.setattr(files, "_BACKEND_CWD", tmp_path)

    r = client.get(f"/api/files/serve", params={"path": "abc.py"})
    assert r.status_code == 200
    assert "print('hi')" in r.text


def test_serve_rejects_path_traversal(client):
    """拒绝 ../ 路径穿越 — 解析后必须在白名单, 否则 403/404"""
    # 从 backend cwd 出发 ../../../etc/passwd 解析到 /etc/passwd (macOS 存在) → 应 403
    r = client.get(f"/api/files/serve", params={"path": "/etc/passwd"})
    assert r.status_code == 403, f'expected 403 (blocked), got {r.status_code}' 


def test_serve_rejects_system_dirs(client):
    """拒绝 /etc /private/etc 等系统目录"""
    r = client.get(f"/api/files/serve", params={"path": "/etc/passwd"})
    assert r.status_code in (400, 403, 404)


def test_serve_rejects_ssh(client):
    """拒绝 ~/.ssh"""
    r = client.get(f"/api/files/serve", params={"path": str(Path.home() / ".ssh" / "id_rsa")})
    assert r.status_code in (400, 403, 404)


def test_serve_nonexistent(client, tmp_path, monkeypatch):
    """不存在的文件 404"""
    from app.api import files
    monkeypatch.setattr(files, "_BACKEND_CWD", tmp_path)

    r = client.get(f"/api/files/serve", params={"path": "nope.txt"})
    assert r.status_code == 404


def test_serve_empty_path(client):
    """空 path 400"""
    r = client.get(f"/api/files/serve", params={"path": ""})
    assert r.status_code == 400


def test_serve_info(client, tmp_path):
    """info 端点返回元信息"""
    p = tmp_path / "info.txt"
    p.write_text("hello world", encoding="utf-8")

    r = client.get(f"/api/files/info", params={"path": str(p)})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "info.txt"
    assert data["size"] == 11
    assert data["exists"] is True


def test_serve_image_mime(client, tmp_path):
    """图片文件 mime 正确"""
    p = tmp_path / "test.png"
    # 1x1 PNG
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    r = client.get(f"/api/files/serve", params={"path": str(p)})
    assert r.status_code == 200
    assert "image/png" in r.headers.get("content-type", "")
