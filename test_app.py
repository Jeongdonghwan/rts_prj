import base64
import json
import os

from app import app


def test_site(tmp_path=None):
    import tempfile
    from pathlib import Path

    out = Path(tempfile.mkdtemp()) / "inq.jsonl"
    app.config["INQUIRIES"] = out
    app.config["DB"] = out.with_name("qna.db")
    c = app.test_client()

    for url in ("/", "/about", "/oem", "/facility", "/contact", "/qna", "/qna/write"):
        assert c.get(url).status_code == 200, url
    assert c.get("/nope").status_code == 404

    ok = {"name": "홍길동", "phone": "010-0000-0000", "message": "=문의", "agree": "1"}
    assert c.post("/contact", data={**ok, "name": ""}).status_code == 400
    assert c.post("/contact", data={**ok, "phone": ""}).status_code == 400  # 연락 수단 없음
    assert c.post("/contact", data={k: v for k, v in ok.items() if k != "agree"}).status_code == 400
    assert c.post("/contact", data={**ok, "website": "bot"}).status_code == 302  # honeypot: 저장 안 함
    assert not out.exists()

    assert c.post("/contact", data=ok).status_code == 302
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["name"] == "홍길동"

    def basic(pw):
        return {"Authorization": "Basic " + base64.b64encode(f"admin:{pw}".encode()).decode()}

    os.environ.pop("ADMIN_PASSWORD", None)
    assert c.get("/admin", headers=basic("1234")).status_code == 200  # 미설정이면 초안용 기본값
    os.environ["ADMIN_PASSWORD"] = "s3cret"
    assert c.get("/admin").status_code == 401
    assert c.get("/admin", headers=basic("wrong")).status_code == 401
    r = c.get("/admin", headers=basic("s3cret"))
    assert r.status_code == 200 and "홍길동" in r.get_data(as_text=True)

    # Q&A: 공개글 / 비밀글
    assert c.post("/qna/write", data={"name": "김", "title": "", "body": "x"}).status_code == 400
    c.post("/qna/write", data={"name": "김공개", "title": "공개제목", "body": "공개본문"})
    c.post("/qna/write", data={"name": "이비밀", "title": "숨긴제목", "body": "숨긴본문", "password": "pw!"})
    page = c.get("/qna").get_data(as_text=True)
    assert "공개제목" in page and "숨긴제목" not in page and "김공개" not in page  # 비밀글 제목·작성자 실명은 목록에 안 나옴
    assert "공개본문" in c.get("/qna/1").get_data(as_text=True)
    assert "숨긴본문" not in c.get("/qna/2").get_data(as_text=True)
    r = c.post("/qna/2", data={"password": "nope"})
    assert r.status_code == 403 and "숨긴본문" not in r.get_data(as_text=True)
    assert "숨긴본문" in c.post("/qna/2", data={"password": "pw!"}).get_data(as_text=True)
    assert c.get("/qna/999").status_code == 404
    assert c.get("/qna?page=99999999999999999999999").status_code == 200

    # 어드민: 비밀글 열람, 답변, 삭제 (Origin 없는 요청은 거부)
    h = basic("s3cret")
    assert c.get("/admin/qna/2").status_code == 401
    assert "숨긴본문" in c.get("/admin/qna/2", headers=h).get_data(as_text=True)
    assert c.post("/admin/qna/2", headers=h, data={"action": "answer", "answer": "답변드립니다"}).status_code == 403
    ho = {**h, "Origin": "http://localhost"}
    assert c.post("/admin/qna/2", headers=ho, data={"action": "answer", "answer": "답변드립니다"}).status_code == 302
    assert "답변드립니다" in c.post("/qna/2", data={"password": "pw!"}).get_data(as_text=True)
    assert "답변완료" in c.get("/qna").get_data(as_text=True)
    assert c.post("/admin/qna/1", headers=ho, data={"action": "delete"}).status_code == 302
    assert c.get("/qna/1").status_code == 404

    # 공지: 어드민만 등록, 목록 맨 위 고정, 수정
    assert c.post("/admin", headers=h, data={"title": "휴무 안내", "body": "연휴 휴무"}).status_code == 403  # Origin 없음
    assert c.post("/admin", headers=ho, data={"title": "휴무 안내", "body": "연휴 휴무"}).status_code == 302
    page = c.get("/qna").get_data(as_text=True)
    assert "휴무 안내" in page and page.index("휴무 안내") < page.index("비밀글입니다")
    assert "RTS COSMETIC · " in c.get("/qna/3").get_data(as_text=True)  # 공지 작성자는 가리지 않음
    assert c.post("/admin/qna/3", headers=ho, data={"action": "edit", "title": "수정된 공지", "body": "본문"}).status_code == 302
    assert "수정된 공지" in c.get("/qna").get_data(as_text=True)


if __name__ == "__main__":
    test_site()
    print("ok")
