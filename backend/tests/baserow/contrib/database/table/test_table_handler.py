import os
import random

import pytest
from unittest.mock import patch

from django.core.files.storage import FileSystemStorage
from django.db import connection
from django.conf import settings
from decimal import Decimal

from pyinstrument import Profiler

from baserow.contrib.database.fields.handler import FieldHandler
from baserow.contrib.database.management.commands.fill_table_rows import fill_table_rows
from baserow.core.exceptions import UserNotInGroup
from baserow.contrib.database.fields.exceptions import (
    MaxFieldLimitExceeded,
    MaxFieldNameLengthExceeded,
)
from baserow.contrib.database.table.models import Table
from baserow.contrib.database.table.handler import TableHandler
from baserow.contrib.database.table.exceptions import (
    TableDoesNotExist,
    TableNotInDatabase,
    InvalidInitialTableData,
    InitialTableDataLimitExceeded,
)
from baserow.contrib.database.fields.models import (
    TextField,
    LongTextField,
    BooleanField,
)
from baserow.contrib.database.views.models import GridView, GridViewFieldOptions
from baserow.core.handler import CoreHandler
from baserow.core.models import TrashEntry
from baserow.core.trash.handler import TrashHandler


@pytest.mark.django_db
def test_get_database_table(data_fixture):
    user = data_fixture.create_user()
    table = data_fixture.create_database_table(user=user)
    data_fixture.create_database_table()
    handler = TableHandler()

    with pytest.raises(TableDoesNotExist):
        handler.get_table(table_id=99999)

    # If the error is raised we know for sure that the base query has resolved.
    with pytest.raises(AttributeError):
        handler.get_table(
            table_id=table.id, base_queryset=Table.objects.prefetch_related("UNKNOWN")
        )

    table_copy = handler.get_table(table_id=table.id)
    assert table_copy.id == table.id

    TrashHandler.trash(user, table.database.group, table.database, table.database)

    with pytest.raises(TableDoesNotExist):
        handler.get_table(table_id=table.id)

    TrashHandler.restore_item(user, "application", table.database.id)

    TrashHandler.trash(user, table.database.group, None, table.database.group)
    with pytest.raises(TableDoesNotExist):
        handler.get_table(table_id=table.id)


@pytest.mark.django_db
@patch("baserow.contrib.database.table.signals.table_created.send")
def test_create_database_table(send_mock, data_fixture):
    user = data_fixture.create_user()
    user_2 = data_fixture.create_user()
    database = data_fixture.create_database_application(user=user)

    handler = TableHandler()
    handler.create_table(user=user, database=database, name="Test table")

    assert Table.objects.all().count() == 1
    assert TextField.objects.all().count() == 1

    table = Table.objects.all().first()
    assert table.name == "Test table"
    assert table.order == 1
    assert table.database == database

    primary_field = TextField.objects.all().first()
    assert primary_field.table == table
    assert primary_field.primary
    assert primary_field.name == "Name"

    send_mock.assert_called_once()
    assert send_mock.call_args[1]["table"].id == table.id
    assert send_mock.call_args[1]["user"].id == user.id

    with pytest.raises(UserNotInGroup):
        handler.create_table(user=user_2, database=database, name="")

    assert f"database_table_{table.id}" in connection.introspection.table_names()

    model = table.get_model(attribute_names=True)
    row = model.objects.create(name="Test")
    assert row.name == "Test"

    with pytest.raises(TypeError):
        model.objects.create(does_not_exists=True)

    assert model.objects.count() == 1
    row = model.objects.get(id=row.id)
    assert row.name == "Test"


@pytest.mark.django_db
def test_fill_example_table_data(data_fixture):
    user = data_fixture.create_user()
    database = data_fixture.create_database_application(user=user)

    table_handler = TableHandler()
    table = table_handler.create_table(
        user, database, fill_example=True, name="Table 1"
    )

    assert Table.objects.all().count() == 1
    assert GridView.objects.all().count() == 1
    assert TextField.objects.all().count() == 1
    assert LongTextField.objects.all().count() == 1
    assert BooleanField.objects.all().count() == 1
    assert GridViewFieldOptions.objects.all().count() == 2

    model = table.get_model()
    results = model.objects.all()

    assert len(results) == 2
    assert results[0].order == Decimal("1.00000000000000000000")
    assert results[1].order == Decimal("2.00000000000000000000")


@pytest.mark.django_db
def test_fill_table_with_initial_data(data_fixture):
    user = data_fixture.create_user()
    database = data_fixture.create_database_application(user=user)

    table_handler = TableHandler()

    with pytest.raises(InvalidInitialTableData):
        table_handler.create_table(user, database, name="Table 1", data=[])

    with pytest.raises(InvalidInitialTableData):
        table_handler.create_table(user, database, name="Table 1", data=[[]])

    limit = settings.INITIAL_TABLE_DATA_LIMIT
    settings.INITIAL_TABLE_DATA_LIMIT = 2

    with pytest.raises(InitialTableDataLimitExceeded):
        table_handler.create_table(user, database, name="Table 1", data=[[], [], []])

    settings.INITIAL_TABLE_DATA_LIMIT = limit

    field_limit = settings.MAX_FIELD_LIMIT
    settings.MAX_FIELD_LIMIT = 2

    with pytest.raises(MaxFieldLimitExceeded):
        table_handler.create_table(
            user,
            database,
            name="Table 1",
            data=[["field1", "field2", "field3"], ["rows"] * 3],
        )

    settings.MAX_FIELD_LIMIT = field_limit

    data = [
        ["A", "B", "C", "D"],
        ["1-1", "1-2", "1-3", "1-4", "1-5"],
        ["2-1", "2-2", "2-3"],
        ["3-1", "3-2"],
    ]
    table = table_handler.create_table(
        user, database, name="Table 1", data=data, first_row_header=True
    )

    text_fields = TextField.objects.filter(table=table)
    assert text_fields[0].name == "A"
    assert text_fields[1].name == "B"
    assert text_fields[2].name == "C"
    assert text_fields[3].name == "D"
    assert text_fields[4].name == "Field 5"

    assert GridView.objects.all().count() == 1

    model = table.get_model()
    results = model.objects.all()

    assert results[0].order == Decimal("1.00000000000000000000")
    assert results[1].order == Decimal("2.00000000000000000000")
    assert results[2].order == Decimal("3.00000000000000000000")

    assert getattr(results[0], f"field_{text_fields[0].id}") == "1-1"
    assert getattr(results[0], f"field_{text_fields[1].id}") == "1-2"
    assert getattr(results[0], f"field_{text_fields[2].id}") == "1-3"
    assert getattr(results[0], f"field_{text_fields[3].id}") == "1-4"
    assert getattr(results[0], f"field_{text_fields[4].id}") == "1-5"

    assert getattr(results[1], f"field_{text_fields[0].id}") == "2-1"
    assert getattr(results[1], f"field_{text_fields[1].id}") == "2-2"
    assert getattr(results[1], f"field_{text_fields[2].id}") == "2-3"
    assert getattr(results[1], f"field_{text_fields[3].id}") == ""
    assert getattr(results[1], f"field_{text_fields[4].id}") == ""

    assert getattr(results[2], f"field_{text_fields[0].id}") == "3-1"
    assert getattr(results[2], f"field_{text_fields[1].id}") == "3-2"
    assert getattr(results[2], f"field_{text_fields[2].id}") == ""
    assert getattr(results[2], f"field_{text_fields[3].id}") == ""
    assert getattr(results[2], f"field_{text_fields[4].id}") == ""

    data = [
        ["1-1"],
        ["2-1", "2-2", "2-3"],
        ["3-1", "3-2"],
    ]
    table = table_handler.create_table(
        user, database, name="Table 2", data=data, first_row_header=False
    )

    text_fields = TextField.objects.filter(table=table)
    assert text_fields[0].name == "Field 1"
    assert text_fields[1].name == "Field 2"
    assert text_fields[2].name == "Field 3"

    assert GridView.objects.all().count() == 2

    model = table.get_model()
    results = model.objects.all()

    assert getattr(results[0], f"field_{text_fields[0].id}") == "1-1"
    assert getattr(results[0], f"field_{text_fields[1].id}") == ""
    assert getattr(results[0], f"field_{text_fields[2].id}") == ""

    assert getattr(results[1], f"field_{text_fields[0].id}") == "2-1"
    assert getattr(results[1], f"field_{text_fields[1].id}") == "2-2"
    assert getattr(results[1], f"field_{text_fields[2].id}") == "2-3"

    assert getattr(results[2], f"field_{text_fields[0].id}") == "3-1"
    assert getattr(results[2], f"field_{text_fields[1].id}") == "3-2"

    field_limit = settings.MAX_FIELD_LIMIT
    settings.MAX_FIELD_LIMIT = 5
    data = [
        ["A", "B", "C", "D", "E"],
        ["1-1", "1-2", "1-3", "1-4", "1-5"],
    ]
    table = table_handler.create_table(
        user, database, name="Table 3", data=data, first_row_header=True
    )
    num_fields = table.field_set.count()

    assert GridView.objects.all().count() == 3
    assert num_fields == settings.MAX_FIELD_LIMIT

    settings.MAX_FIELD_LIMIT = field_limit

    too_long_field_name = "x" * 256
    field_name_with_ok_length = "x" * 255

    data = [
        [too_long_field_name, "B", "C", "D", "E"],
        ["1-1", "1-2", "1-3", "1-4", "1-5"],
    ]

    with pytest.raises(MaxFieldNameLengthExceeded):
        table_handler.create_table(
            user, database, name="Table 3", data=data, first_row_header=True
        )

    data = [
        [field_name_with_ok_length, "B", "C", "D", "E"],
        ["1-1", "1-2", "1-3", "1-4", "1-5"],
    ]
    table = table_handler.create_table(
        user, database, name="Table 3", data=data, first_row_header=True
    )
    num_fields = table.field_set.count()

    assert num_fields == 5


@pytest.mark.django_db
@patch("baserow.contrib.database.table.signals.table_updated.send")
def test_update_database_table(send_mock, data_fixture):
    user = data_fixture.create_user()
    user_2 = data_fixture.create_user()
    group = data_fixture.create_group(user=user)
    database = data_fixture.create_database_application(group=group)
    table = data_fixture.create_database_table(database=database)

    handler = TableHandler()

    with pytest.raises(UserNotInGroup):
        handler.update_table(user=user_2, table=table, name="Test 1")

    handler.update_table(user=user, table=table, name="Test 1")

    send_mock.assert_called_once()
    assert send_mock.call_args[1]["table"].id == table.id
    assert send_mock.call_args[1]["user"].id == user.id

    table.refresh_from_db()

    assert table.name == "Test 1"


@pytest.mark.django_db
@patch("baserow.contrib.database.table.signals.tables_reordered.send")
def test_order_tables(send_mock, data_fixture):
    user = data_fixture.create_user()
    user_2 = data_fixture.create_user()
    database = data_fixture.create_database_application(user=user)
    table_1 = data_fixture.create_database_table(database=database, order=1)
    table_2 = data_fixture.create_database_table(database=database, order=2)
    table_3 = data_fixture.create_database_table(database=database, order=3)

    handler = TableHandler()

    with pytest.raises(UserNotInGroup):
        handler.order_tables(user=user_2, database=database, order=[])

    with pytest.raises(TableNotInDatabase):
        handler.order_tables(user=user, database=database, order=[0])

    handler.order_tables(
        user=user, database=database, order=[table_3.id, table_2.id, table_1.id]
    )
    table_1.refresh_from_db()
    table_2.refresh_from_db()
    table_3.refresh_from_db()
    assert table_1.order == 3
    assert table_2.order == 2
    assert table_3.order == 1

    send_mock.assert_called_once()
    assert send_mock.call_args[1]["database"].id == database.id
    assert send_mock.call_args[1]["user"].id == user.id
    assert send_mock.call_args[1]["order"] == [table_3.id, table_2.id, table_1.id]

    handler.order_tables(
        user=user, database=database, order=[table_1.id, table_3.id, table_2.id]
    )
    table_1.refresh_from_db()
    table_2.refresh_from_db()
    table_3.refresh_from_db()
    assert table_1.order == 1
    assert table_2.order == 3
    assert table_3.order == 2

    handler.order_tables(user=user, database=database, order=[table_1.id])
    table_1.refresh_from_db()
    table_2.refresh_from_db()
    table_3.refresh_from_db()
    assert table_1.order == 1
    assert table_2.order == 0
    assert table_3.order == 0


@pytest.mark.django_db
@patch("baserow.contrib.database.table.signals.table_deleted.send")
def test_delete_database_table(send_mock, data_fixture):
    user = data_fixture.create_user()
    user_2 = data_fixture.create_user()
    group = data_fixture.create_group(user=user)
    database = data_fixture.create_database_application(group=group)
    table = data_fixture.create_database_table(user=user, database=database)

    handler = TableHandler()

    with pytest.raises(UserNotInGroup):
        handler.delete_table(user=user_2, table=table)

    assert Table.objects.all().count() == 1
    assert Table.trash.all().count() == 0

    table_id = table.id
    handler.delete_table(user=user, table=table)

    send_mock.assert_called_once()
    assert send_mock.call_args[1]["table_id"] == table_id
    assert send_mock.call_args[1]["user"].id == user.id

    assert Table.objects.all().count() == 0
    assert Table.trash.all().count() == 1
    assert f"database_table_{table.id}" in connection.introspection.table_names()


@pytest.mark.django_db
@patch("baserow.contrib.database.fields.signals.field_updated.send")
@patch("baserow.contrib.database.table.signals.table_deleted.send")
def test_deleting_table_trashes_all_fields_and_any_related_links(
    table_deleted_send_mock, field_updated_send_mock, data_fixture
):
    user = data_fixture.create_user()
    table_a, table_b, link_field = data_fixture.create_two_linked_tables(user)
    target_field = data_fixture.create_text_field(user, table=table_b, name="target")

    dependant_field = FieldHandler().create_field(
        user,
        table_a,
        "lookup",
        through_field_id=link_field.id,
        target_field_id=target_field.id,
        name="lookup",
    )
    other_dependant_field = FieldHandler().create_field(
        user, table_a, "formula", name="formula", formula=f'field("{link_field.name}")'
    )
    assert dependant_field.formula_type == "array"
    assert other_dependant_field.formula_type == "array"

    handler = TableHandler()
    handler.delete_table(user, table_b)

    dependant_field.refresh_from_db()
    other_dependant_field.refresh_from_db()
    assert dependant_field.formula_type == "invalid"
    assert other_dependant_field.formula_type == "invalid"

    table_deleted_send_mock.assert_called_once()
    assert table_deleted_send_mock.call_args[1]["table_id"] == table_b.id
    assert table_deleted_send_mock.call_args[1]["user"].id == user.id

    field_updated_send_mock.assert_called_once()
    assert field_updated_send_mock.call_args[1]["field"].id == dependant_field.id
    assert field_updated_send_mock.call_args[1]["user"] is None
    assert field_updated_send_mock.call_args[1]["related_fields"] == [
        other_dependant_field
    ]


@pytest.mark.django_db
def test_deleting_a_table_breaks_dependant_fields_and_sends_updates_for_them(
    data_fixture,
):
    user = data_fixture.create_user()
    table_a, table_b, link_field = data_fixture.create_two_linked_tables(user)

    other_table_b_field = data_fixture.create_long_text_field(
        user, table=table_b, name="other"
    )

    handler = TableHandler()
    handler.delete_table(user, table_b)

    other_table_b_field.refresh_from_db()
    link_field.refresh_from_db()
    assert other_table_b_field.trashed
    assert link_field.trashed
    assert link_field.link_row_related_field.trashed


@pytest.mark.django_db
def test_restoring_a_table_restores_fields_and_related_fields(data_fixture):
    user = data_fixture.create_user()
    table_a, table_b, link_field = data_fixture.create_two_linked_tables(user)

    other_table_b_field = data_fixture.create_long_text_field(
        user, table=table_b, name="other"
    )

    handler = TableHandler()
    handler.delete_table(user, table_b)

    TrashHandler.restore_item(user, "table", table_b.id)

    other_table_b_field.refresh_from_db()
    link_field.refresh_from_db()
    assert not other_table_b_field.trashed
    assert not link_field.trashed
    assert not link_field.trashed
    assert not link_field.link_row_related_field.trashed


@pytest.mark.django_db
def test_restoring_table_with_a_previously_trashed_field_leaves_the_field_trashed(
    data_fixture,
):
    user = data_fixture.create_user()
    table_a, table_b, link_field = data_fixture.create_two_linked_tables(user)

    other_table_b_field = data_fixture.create_long_text_field(
        user, table=table_b, name="other"
    )

    FieldHandler().delete_field(user, other_table_b_field)
    TableHandler().delete_table(user, table_b)

    TrashHandler.restore_item(user, "table", table_b.id)

    other_table_b_field.refresh_from_db()
    link_field.refresh_from_db()
    assert other_table_b_field.trashed
    assert TrashEntry.objects.get(
        trash_item_type="field", trash_item_id=other_table_b_field.id
    )
    assert not link_field.trashed
    assert not link_field.trashed
    assert not link_field.link_row_related_field.trashed


@pytest.mark.django_db
def test_count_rows(data_fixture):
    table = data_fixture.create_database_table()
    grid_view = data_fixture.create_grid_view(table=table)
    field = data_fixture.create_text_field(table=table)
    model = table.get_model()

    count_expected = random.randint(0, 100)

    for i in range(count_expected):
        model.objects.create(**{f"field_{field.id}": i})

    TableHandler().count_rows()

    table.refresh_from_db()
    assert table.row_count == count_expected


@pytest.mark.django_db
def test_count_rows_ignores_templates(data_fixture, tmpdir):
    old_templates = settings.APPLICATION_TEMPLATES_DIR
    settings.APPLICATION_TEMPLATES_DIR = os.path.join(
        settings.BASE_DIR, "../../../tests/templates"
    )

    storage = FileSystemStorage(location=str(tmpdir), base_url="http://localhost")

    # Make sure that some template tables are created
    assert Table.objects.count() == 0
    CoreHandler().sync_templates(storage=storage)
    assert Table.objects.count() > 0

    TableHandler.count_rows()

    for table in Table.objects.all():
        assert table.row_count is None

    settings.APPLICATION_TEMPLATES_DIR = old_templates


@pytest.mark.django_db
@pytest.mark.disabled_in_ci
# You must add --run-disabled-in-ci -s to pytest to run this test, you can do this in
# intellij by editing the run config for this test and adding --run-disabled-in-ci -s
# to additional args.
def test_counting_many_rows_in_many_tables(data_fixture):
    table_amount = 1000
    rows_amount = 2000
    profiler = Profiler()

    # 1000 tables
    for i in range(table_amount):
        table = data_fixture.create_database_table()
        fill_table_rows(rows_amount, table)

    profiler.start()
    TableHandler.count_rows()
    profiler.stop()

    print(profiler.output_text(unicode=True, color=True))
    profiler.reset()

    # 2000 tables
    for i in range(table_amount):
        table = data_fixture.create_database_table()
        fill_table_rows(rows_amount, table)

    profiler.start()
    TableHandler.count_rows()
    profiler.stop()

    print(profiler.output_text(unicode=True, color=True))
    profiler.reset()

    # 3000 tables
    for i in range(table_amount):
        table = data_fixture.create_database_table()
        fill_table_rows(rows_amount, table)

    profiler.start()
    TableHandler.count_rows()
    profiler.stop()

    print(profiler.output_text(unicode=True, color=True))
