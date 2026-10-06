import hmac
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, Response, abort, redirect, render_template, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # nginx 뒤에서 https·도메인 기준으로 URL 생성
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
app.config["INQUIRIES"] = Path(__file__).with_name("inquiries.jsonl")
app.config["DB"] = Path(__file__).with_name("qna.db")

COMPANY = {
    "name": "주식회사 알티에스코스메틱",
    "ceo": "김성호, 장수용",
    "biz_no": "764-86-02538",
    "address": "인천광역시 남동구 남동서로270번길 16, 4층(논현동)",
    "email": "rtscos01@naver.com",
}

TURNKEY = ["제품개발", "용기 선택", "제품 디자인 확정", "제조 진행", "충진 및 포장 준비", "완제품 포장 및 배송"]

CERTS = [
    ("ISO 22716", "국제 화장품 우수제조관리기준 · Bureau Veritas"),
    ("CGMP", "우수 화장품 제조 및 품질관리기준 적합업소 · 식품의약품안전처"),
    ("EVE VEGAN", "비건 화장품 생산 공장 인증"),
]

COUNTRIES = ["미국", "일본", "아랍에미리트", "콜롬비아", "브라질", "필리핀", "베트남", "태국", "중국", "인도네시아"]

FAQ = [
    ("최소 주문 수량(MOQ)은 얼마인가요?", "소량 제조의 경우 MOQ 1,000개부터 가능합니다."),
    ("용기가 준비되어 있지 않아도 진행할 수 있나요?",
     "대부분의 화장품 용기는 발주 MOQ가 5,000~10,000개입니다. 수량이 부담스러우시면 당사 보유 용기와 자체 인쇄 설비를 이용해 용기 재고 부담 없이 소량으로 진행하실 수 있습니다."),
    ("어떤 제품을 제조할 수 있나요?", "스킨케어, 바디케어, 베이스 메이크업을 전문으로 제조하며 마스크팩 제조 라인을 별도로 보유하고 있습니다."),
    ("샘플은 얼마나 빨리 받아볼 수 있나요?", "다양한 제형 데이터를 보유하고 있어 빠른 샘플링이 가능합니다. 타겟 제품과 일정을 알려주시면 상세히 안내드립니다."),
    ("어떤 인증을 보유하고 있나요?", "ISO 22716(Bureau Veritas), CGMP, EVE VEGAN 공장 인증을 보유하고 있습니다."),
    ("수출용 제품도 제조할 수 있나요?", "미국, 일본, 아랍에미리트, 중국, 동남아 등 10개국 이상에 수출하고 있습니다."),
]

FIELDS = {"company": 100, "name": 50, "phone": 30, "email": 100, "category": 30, "quantity": 30, "message": 3000}
POST_FIELDS = {"name": 30, "title": 100, "body": 3000}
PER_PAGE = 15


def db():
    con = sqlite3.connect(app.config["DB"])
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
        pw_hash TEXT, created TEXT NOT NULL, answer TEXT, answered TEXT, notice INTEGER NOT NULL DEFAULT 0)""")
    try:  # 공지 컬럼이 없는 예전 DB 파일 보정
        con.execute("ALTER TABLE posts ADD COLUMN notice INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    return con


def get_post(post_id):
    with closing(db()) as con:
        post = con.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    return post or abort(404)


def now():
    return datetime.now().isoformat(sep=" ", timespec="minutes")


def is_admin():
    # ponytail: 초안용 기본 비밀번호 1234. 실제 배포 전에 환경변수 ADMIN_PASSWORD로 반드시 교체
    password = os.environ.get("ADMIN_PASSWORD") or "1234"
    auth = request.authorization
    # ponytail: 로그인 시도 횟수 제한 없음. 긴 비밀번호 + HTTPS 전제, 필요해지면 rate limit 추가
    return bool(auth and auth.username == "admin" and hmac.compare_digest((auth.password or "").encode(), password.encode()))


def need_login():
    return Response("로그인이 필요합니다.", 401, {"WWW-Authenticate": 'Basic realm="RTS admin"'})


def same_origin():
    # Basic 인증은 브라우저가 자동으로 붙이므로, 다른 사이트에서 보낸 요청(CSRF)은 Origin으로 걸러냄
    return urlparse(request.headers.get("Origin", "")).netloc == request.host


@app.context_processor
def common():
    return dict(company=COMPANY, turnkey=TURNKEY, certs=CERTS, countries=COUNTRIES, faq=FAQ)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/<page>")
def page(page):
    if page not in ("about", "oem", "facility"):
        abort(404)
    return render_template(f"{page}.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "GET":
        return render_template("contact.html", form={}, error=None)
    if request.form.get("website"):  # honeypot: 사람 눈에 안 보이는 칸을 채웠으면 봇
        return redirect(url_for("contact", sent=1))
    form = {k: request.form.get(k, "").strip()[:n] for k, n in FIELDS.items()}
    error = None
    if not form["name"] or not form["message"]:
        error = "담당자명과 문의 내용을 입력해 주세요."
    elif not (form["phone"] or form["email"]):
        error = "연락처 또는 이메일 중 하나는 입력해 주세요."
    elif form["email"] and "@" not in form["email"]:
        error = "이메일 형식을 확인해 주세요."
    elif not request.form.get("agree"):
        error = "개인정보 수집·이용에 동의해 주세요."
    if error:
        return render_template("contact.html", form=form, error=error), 400
    form["at"] = datetime.now().isoformat(timespec="seconds")
    with open(app.config["INQUIRIES"], "a", encoding="utf-8") as f:
        f.write(json.dumps(form, ensure_ascii=False) + "\n")
    return redirect(url_for("contact", sent=1))


# ----- Q&A 게시판 (비로그인, 비밀번호를 넣으면 비밀글) -----

@app.route("/qna")
def qna():
    with closing(db()) as con:
        total = con.execute("SELECT COUNT(*) FROM posts WHERE notice = 0").fetchone()[0]
        pages = max(-(-total // PER_PAGE), 1)
        page = min(max(request.args.get("page", 1, type=int), 1), pages)
        notices = con.execute("SELECT id, title, created FROM posts WHERE notice = 1 ORDER BY id DESC").fetchall()
        rows = con.execute(
            "SELECT id, name, title, pw_hash IS NOT NULL AS secret, created, answer IS NOT NULL AS answered "
            "FROM posts WHERE notice = 0 ORDER BY id DESC LIMIT ? OFFSET ?", (PER_PAGE, (page - 1) * PER_PAGE)).fetchall()
    return render_template("qna.html", rows=rows, notices=notices, page=page, pages=pages, total=total)


@app.route("/qna/write", methods=["GET", "POST"])
def qna_write():
    if request.method == "GET":
        return render_template("qna_write.html", form={}, error=None)
    if request.form.get("website"):  # honeypot
        return redirect(url_for("qna"))
    form = {k: request.form.get(k, "").strip()[:n] for k, n in POST_FIELDS.items()}
    if not all(form.values()):
        return render_template("qna_write.html", form=form, error="이름, 제목, 내용을 모두 입력해 주세요."), 400
    password = request.form.get("password", "")[:50]
    # ponytail: 글쓰기 횟수 제한 없음(honeypot만). 스팸이 실제로 들어오면 IP당 제한이나 캡차 추가
    with closing(db()) as con, con:
        con.execute("INSERT INTO posts (name, title, body, pw_hash, created) VALUES (?, ?, ?, ?, ?)",
                    (form["name"], form["title"], form["body"], generate_password_hash(password) if password else None, now()))
    return redirect(url_for("qna"))


@app.route("/qna/<int:post_id>", methods=["GET", "POST"])
def qna_view(post_id):
    post = get_post(post_id)
    locked, error = bool(post["pw_hash"]), None
    if locked and request.method == "POST":
        if check_password_hash(post["pw_hash"], request.form.get("password", "")):
            locked = False
        else:
            error = "비밀번호가 일치하지 않습니다."
    return render_template("qna_view.html", post=post, locked=locked, error=error, admin=False), 403 if error else 200


# ----- 어드민 -----

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not is_admin():
        return need_login()
    if request.method == "POST":  # 공지 등록
        if not same_origin():
            abort(403)
        title, body = request.form.get("title", "").strip()[:100], request.form.get("body", "").strip()[:3000]
        if title and body:
            with closing(db()) as con, con:
                con.execute("INSERT INTO posts (name, title, body, created, notice) VALUES ('RTS COSMETIC', ?, ?, ?, 1)", (title, body, now()))
        return redirect(url_for("admin"))
    path = app.config["INQUIRIES"]
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    with closing(db()) as con:
        posts = con.execute("SELECT id, name, title, created, notice, answer IS NOT NULL AS answered FROM posts ORDER BY notice DESC, id DESC").fetchall()
    return render_template("admin.html", rows=[json.loads(line) for line in reversed(lines)], posts=posts)


@app.route("/admin/qna/<int:post_id>", methods=["GET", "POST"])
def admin_qna(post_id):
    if not is_admin():
        return need_login()
    post = get_post(post_id)
    if request.method == "POST":
        if not same_origin():
            abort(403)
        action = request.form.get("action")
        with closing(db()) as con, con:
            if action == "delete":
                con.execute("DELETE FROM posts WHERE id = ?", (post_id,))
                return redirect(url_for("admin"))
            if action == "edit":  # 공지 수정
                title, body = request.form.get("title", "").strip()[:100], request.form.get("body", "").strip()[:3000]
                if title and body:
                    con.execute("UPDATE posts SET title = ?, body = ? WHERE id = ?", (title, body, post_id))
                return redirect(url_for("admin_qna", post_id=post_id))
            answer = request.form.get("answer", "").strip()[:3000]
            con.execute("UPDATE posts SET answer = ?, answered = ? WHERE id = ?", (answer or None, now() if answer else None, post_id))
        return redirect(url_for("admin_qna", post_id=post_id))
    return render_template("qna_view.html", post=post, locked=False, error=None, admin=True)


if __name__ == "__main__":
    app.run(debug=True)
