import pytest
from unittest.mock import MagicMock

import app.es.es_audio_admin as es_admin
from app.es.es_audio_admin import ESKeywordHit


# -------------------------
# 通用 fixture：Mock ES
# -------------------------
@pytest.fixture
def mock_es(monkeypatch):
    es = MagicMock()

    # indices API
    es.indices.exists.return_value = False
    es.indices.create.return_value = {"acknowledged": True}
    es.indices.delete.return_value = {"acknowledged": True}

    # search / delete / update
    es.search.return_value = {
        "hits": {
            "hits": []
        }
    }
    es.delete_by_query.return_value = {"deleted": 0}
    es.update_by_query.return_value = {"updated": 0}

    # patch es_client()
    monkeypatch.setattr(es_admin, "es_client", lambda: es)

    return es


# -------------------------
# ensure_audio_index
# -------------------------
def test_ensure_audio_index_create(mock_es):
    mock_es.indices.exists.return_value = False

    es_admin.ensure_audio_index()

    mock_es.indices.create.assert_called_once()
    mock_es.indices.exists.assert_called_once()


def test_ensure_audio_index_exists(mock_es):
    mock_es.indices.exists.return_value = True

    es_admin.ensure_audio_index()

    mock_es.indices.create.assert_not_called()


# -------------------------
# upsert_audio_segments
# -------------------------
def test_upsert_audio_segments(monkeypatch, mock_es):
    # mock helpers.bulk
    monkeypatch.setattr(
        es_admin.helpers,
        "bulk",
        lambda es, actions, refresh: (len(actions), [])
    )

    rows = [
        {
            "segment_id": "seg1",
            "segment_idx": 0,
            "start_ms": 0,
            "end_ms": 1000,
            "text": "你好 世界",
            "visibility": "public",
        },
        {
            "segment_id": "seg2",
            "segment_idx": 1,
            "start_ms": 1000,
            "end_ms": 2000,
            "text": "测试 音频",
            "visibility": "private",
        },
    ]

    ok = es_admin.upsert_audio_segments(
        audio_id="audio1",
        rows=rows,
    )

    assert ok == 2


def test_upsert_audio_segments_empty(monkeypatch, mock_es):
    monkeypatch.setattr(
        es_admin.helpers,
        "bulk",
        lambda es, actions, refresh: (0, [])
    )

    ok = es_admin.upsert_audio_segments(
        audio_id="audio1",
        rows=[],
    )

    assert ok == 0


# -------------------------
# delete_by_audio_id
# -------------------------
def test_delete_by_audio_id(mock_es):
    mock_es.delete_by_query.return_value = {"deleted": 3}

    deleted = es_admin.delete_by_audio_id("audio1")

    assert deleted == 3
    mock_es.delete_by_query.assert_called_once()


# -------------------------
# delete_many_audio_ids
# -------------------------
def test_delete_many_audio_ids(monkeypatch):
    monkeypatch.setattr(
        es_admin,
        "delete_by_audio_id",
        lambda aid: 2 if aid == "a1" else 0
    )

    result = es_admin.delete_many_audio_ids(["a1", "a2", ""])

    assert result == {
        "a1": 2,
        "a2": 0,
    }


# -------------------------
# update_visibility_by_audio_id
# -------------------------
def test_update_visibility_by_audio_id(mock_es):
    mock_es.update_by_query.return_value = {"updated": 5}

    updated = es_admin.update_visibility_by_audio_id(
        audio_id="audio1",
        visibility="private",
    )

    assert updated == 5
    mock_es.update_by_query.assert_called_once()


# -------------------------
# keyword_search
# -------------------------
def test_keyword_search(mock_es):
    mock_es.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_score": 1.23,
                    "_source": {
                        "audio_id": "audio1",
                        "segment_id": "seg1",
                        "segment_idx": 0,
                        "start_ms": 0,
                        "end_ms": 1000,
                        "text": "你好 世界",
                    },
                }
            ]
        }
    }

    hits = es_admin.keyword_search(
        q="你好",
        k=5,
        allowed_visibilities=["public"],
    )

    assert len(hits) == 1
    hit = hits[0]

    assert isinstance(hit, ESKeywordHit)
    assert hit.audio_id == "audio1"
    assert hit.segment_idx == 0
    assert hit.score == 1.23
