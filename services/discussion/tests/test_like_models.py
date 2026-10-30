from app.models import ThreadLike, CommentLike


def test_thread_like_table():
    assert ThreadLike.__tablename__ == "thread_like"

    primary_key_columns = {
        column.name
        for column in ThreadLike.__table__.primary_key.columns
    }

    assert primary_key_columns == {"user_id", "thread_id"}


def test_comment_like_table():
    assert CommentLike.__tablename__ == "comment_like"

    primary_key_columns = {
        column.name
        for column in CommentLike.__table__.primary_key.columns
    }

    assert primary_key_columns == {"user_id", "comment_id"}


def test_like_models_have_created_at():
    assert "created_at" in ThreadLike.__table__.columns
    assert "created_at" in CommentLike.__table__.columns

    