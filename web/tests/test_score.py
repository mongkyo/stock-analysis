"""
[tests/test_score.py] _recalc_scores() 단위 테스트
─────────────────────────────────────────────────
DB 없이 순수 로직만 검증:
- 점수 계산 및 내림차순 정렬
- None 값(ROE/OPM 미존재) 처리
- rank 재할당
- 빈 리스트 처리
"""
from api.routers.dashboard import _recalc_scores, _ResultRow, _FakeAR


def _row(rank, code, growth, roe=None, opm=None):
    """테스트용 _ResultRow 생성 헬퍼"""
    ar = _FakeAR(rank, code, f"종목{code}", growth, roe, opm, "20260101", "20260131")
    return _ResultRow(ar, 1000, int(1000 * (1 + growth / 100)))


class TestRecalcScoresBasic:
    def test_sorted_by_score_descending(self):
        """점수 높은 종목이 앞에 와야 함"""
        rows = [
            _row(1, "000001", 50.0, roe=20.0, opm=15.0),  # 최고
            _row(2, "000002", 10.0, roe=5.0,  opm=3.0),   # 최저
            _row(3, "000003", 30.0, roe=10.0, opm=8.0),   # 중간
        ]
        result = _recalc_scores(rows)
        assert result[0].code == "000001"
        assert result[2].code == "000002"

    def test_rank_reassigned_sequentially(self):
        """점수 재계산 후 rank가 1부터 순서대로 부여되어야 함"""
        rows = [_row(3, "A", 5.0), _row(1, "B", 30.0), _row(2, "C", 15.0)]
        result = _recalc_scores(rows)
        assert [r.rank for r in result] == [1, 2, 3]

    def test_score_is_set(self):
        """score 값이 None이 아닌 숫자여야 함"""
        rows = [_row(1, "A", 20.0, roe=10.0, opm=5.0)]
        result = _recalc_scores(rows)
        assert result[0].score is not None
        assert isinstance(result[0].score, float)

    def test_score_between_0_and_100(self):
        """점수는 백분위 기반이므로 0~100 범위"""
        rows = [_row(i, str(i), float(i * 10), roe=float(i), opm=float(i)) for i in range(1, 6)]
        result = _recalc_scores(rows)
        for r in result:
            assert 0 <= r.score <= 100


class TestRecalcScoresNullHandling:
    def test_all_none_roe_opm(self):
        """ROE/OPM 전부 None이어도 오류 없이 처리"""
        rows = [
            _row(1, "A", 50.0, roe=None, opm=None),
            _row(2, "B", 10.0, roe=None, opm=None),
        ]
        result = _recalc_scores(rows)
        assert len(result) == 2
        assert all(r.score is not None for r in result)

    def test_partial_none(self):
        """일부만 None이어도 중앙값으로 대체해 처리"""
        rows = [
            _row(1, "A", 30.0, roe=15.0, opm=None),
            _row(2, "B", 20.0, roe=None, opm=5.0),
            _row(3, "C", 10.0, roe=10.0, opm=3.0),
        ]
        result = _recalc_scores(rows)
        assert len(result) == 3

    def test_single_row(self):
        """단일 종목 — 순위 1, score 계산됨"""
        result = _recalc_scores([_row(5, "A", 20.0, roe=10.0, opm=5.0)])
        assert len(result) == 1
        assert result[0].rank == 1

    def test_empty_list(self):
        """빈 리스트 → 빈 리스트 반환"""
        assert _recalc_scores([]) == []


class TestRecalcScoresWeights:
    def test_high_growth_beats_high_roe(self):
        """수익률 가중치(70%)가 ROE(15%)보다 높아야 함"""
        # A: 수익률 최고, ROE 낮음
        # B: 수익률 낮음, ROE 최고
        rows = [
            _row(1, "A", 80.0, roe=2.0,  opm=2.0),
            _row(2, "B", 5.0,  roe=50.0, opm=40.0),
        ]
        result = _recalc_scores(rows)
        assert result[0].code == "A"  # 수익률 높은 A가 1등
