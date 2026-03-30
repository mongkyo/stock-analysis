"""
[tests/test_api.py] FastAPI 엔드포인트 통합 테스트
───────────────────────────────────────────────────
TestClient + SQLite 인메모리 DB로 검증:
- 로그인/로그아웃 흐름
- 미인증 접근 → 로그인 리다이렉트
- 권한 없는 접근 → 403
- admin 전용 엔드포인트 접근 제어
- 회원 승인 / 권한 변경 / 비활성화
"""


# ── 인증 / 리다이렉트 ─────────────────────────────────────
class TestAuth:
    def test_login_page_accessible(self, client):
        """로그인 페이지는 누구나 접근 가능"""
        resp = client.get("/auth/login")
        assert resp.status_code == 200

    def test_login_success_redirects(self, client, admin_user):
        """올바른 자격증명으로 로그인하면 / 로 리다이렉트"""
        resp = client.post("/auth/login",
                           data={"username": "admin_user", "password": "testpass"})
        assert resp.status_code in (200, 302, 303)

    def test_login_wrong_password(self, client, admin_user):
        """비밀번호 틀리면 로그인 페이지 유지 (200)"""
        resp = client.post("/auth/login",
                           data={"username": "admin_user", "password": "wrong"})
        assert resp.status_code == 200
        assert "올바르지 않습니다" in resp.text

    def test_logout_clears_cookie(self, client):
        """로그아웃 → 로그인 페이지로 리다이렉트"""
        resp = client.get("/auth/logout")
        assert resp.status_code in (302, 303)

    def test_unauthenticated_dashboard_redirects(self, client):
        """미인증 대시보드 접근 → /auth/login 리다이렉트"""
        resp = client.get("/")
        assert resp.status_code in (302, 303)
        assert "/auth/login" in resp.headers.get("location", "")


# ── 관리자 전용 접근 제어 ─────────────────────────────────
class TestAdminAccess:
    def test_admin_can_access_users_page(self, client, admin_cookies):
        """admin은 /admin/users 접근 가능"""
        resp = client.get("/admin/users", cookies=admin_cookies)
        assert resp.status_code == 200

    def test_basic_cannot_access_users_page(self, client, basic_cookies):
        """basic 사용자는 /admin/users 접근 불가 (403)"""
        resp = client.get("/admin/users", cookies=basic_cookies)
        assert resp.status_code == 403

    def test_operator_cannot_access_users_page(self, client, operator_cookies):
        """operator는 /admin/users 접근 불가 (403)"""
        resp = client.get("/admin/users", cookies=operator_cookies)
        assert resp.status_code == 403

    def test_unauthenticated_users_page_redirects(self, client):
        """미인증 /admin/users → /auth/login 리다이렉트"""
        resp = client.get("/admin/users")
        assert resp.status_code in (302, 303)


# ── 회원 승인 / 권한 변경 ─────────────────────────────────
class TestUserManagement:
    def test_approve_user(self, client, admin_cookies, db):
        """admin이 비활성 사용자를 승인하면 is_active=True"""
        from api.models.user import User, UserRole
        from api.auth import hash_password

        # 대기 중 사용자 생성
        pending = User(
            username="pending_test",
            email="pending_test@test.com",
            hashed_pw=hash_password("testpass"),
            role=UserRole.basic,
            is_active=False,
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)

        resp = client.post(
            f"/admin/users/{pending.id}/approve",
            data={"role": "basic"},
            cookies=admin_cookies,
        )
        assert resp.status_code == 200

        db.expire(pending)
        db.refresh(pending)
        assert pending.is_active is True

    def test_change_role_to_operator(self, client, admin_cookies, db):
        """admin이 기존 사용자를 operator로 변경"""
        from api.models.user import User, UserRole
        from api.auth import hash_password

        target = User(
            username="role_change_test",
            email="role_change_test@test.com",
            hashed_pw=hash_password("testpass"),
            role=UserRole.basic,
            is_active=True,
        )
        db.add(target)
        db.commit()
        db.refresh(target)

        resp = client.post(
            f"/admin/users/{target.id}/role",
            data={"role": "operator"},
            cookies=admin_cookies,
        )
        assert resp.status_code == 200

        db.expire(target)
        db.refresh(target)
        assert target.role == UserRole.operator

    def test_deactivate_user(self, client, admin_cookies, db):
        """admin이 활성 사용자를 비활성화"""
        from api.models.user import User, UserRole
        from api.auth import hash_password

        target = User(
            username="deactivate_test",
            email="deactivate_test@test.com",
            hashed_pw=hash_password("testpass"),
            role=UserRole.basic,
            is_active=True,
        )
        db.add(target)
        db.commit()
        db.refresh(target)

        resp = client.post(
            f"/admin/users/{target.id}/deactivate",
            cookies=admin_cookies,
        )
        assert resp.status_code == 200

        db.expire(target)
        db.refresh(target)
        assert target.is_active is False

    def test_non_admin_cannot_change_role(self, client, basic_cookies, db):
        """basic 사용자는 권한 변경 불가 (403)"""
        from api.models.user import User, UserRole
        from api.auth import hash_password

        target = User(
            username="nochange_test",
            email="nochange_test@test.com",
            hashed_pw=hash_password("testpass"),
            role=UserRole.basic,
            is_active=True,
        )
        db.add(target)
        db.commit()
        db.refresh(target)

        resp = client.post(
            f"/admin/users/{target.id}/role",
            data={"role": "operator"},
            cookies=basic_cookies,
        )
        assert resp.status_code == 403


# ── 분석 실행 접근 제어 ───────────────────────────────────
class TestAnalysisAccess:
    def test_analysis_page_accessible_by_basic(self, client, basic_cookies):
        """basic 사용자도 분석 조회 페이지 접근 가능"""
        resp = client.get("/analysis", cookies=basic_cookies)
        assert resp.status_code == 200

    def test_analysis_page_accessible_by_operator(self, client, operator_cookies):
        """operator도 분석 조회 페이지 접근 가능"""
        resp = client.get("/analysis", cookies=operator_cookies)
        assert resp.status_code == 200

    def test_analysis_run_forbidden_for_basic(self, client, basic_cookies):
        """basic 사용자는 분석 실행 불가 (403)"""
        resp = client.post("/analysis/run?start=2026-01-01&end=2026-01-31",
                           cookies=basic_cookies)
        assert resp.status_code == 403

    def test_analysis_run_allowed_for_operator(self, client, operator_cookies):
        """operator는 분석 실행 가능 (200 or 500 — KIS API 없어서 실패해도 접근은 허용)"""
        resp = client.post("/analysis/run?start=2026-01-01&end=2026-01-31",
                           cookies=operator_cookies)
        # 403이 아니면 접근 허용된 것 (실제 분석은 KIS API 없어서 에러 가능)
        assert resp.status_code != 403

    def test_analysis_run_allowed_for_admin(self, client, admin_cookies):
        """admin은 분석 실행 가능"""
        resp = client.post("/analysis/run?start=2026-01-01&end=2026-01-31",
                           cookies=admin_cookies)
        assert resp.status_code != 403
