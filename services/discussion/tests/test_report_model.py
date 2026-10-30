from app.models import Report


def test_report_table_name():
    assert Report.__tablename__ == "report"


def test_report_has_expected_columns():
    expected_columns = {
        "id",
        "reporter_id",
        "target_type",
        "target_id",
        "reason",
        "note",
        "status",
        "created_at",
        "resolved_at",
    }

    actual_columns = set(Report.__table__.columns.keys())

    assert actual_columns == expected_columns


def test_report_has_unique_constraint():
    unique_constraints = [
        constraint
        for constraint in Report.__table__.constraints
        if constraint.name == "uq_reporter_target"
    ]

    assert len(unique_constraints) == 1

    columns = {
        column.name
        for column in unique_constraints[0].columns
    }

    assert columns == {
        "reporter_id",
        "target_type",
        "target_id",
    }


def test_report_optional_fields():
    assert Report.__table__.columns["note"].nullable is True
    assert Report.__table__.columns["resolved_at"].nullable is True


def test_report_has_no_foreign_keys():
    assert len(Report.__table__.foreign_keys) == 0