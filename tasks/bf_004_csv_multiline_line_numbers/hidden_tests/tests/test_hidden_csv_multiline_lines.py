import io

from shopcore.csv_import import import_products, load_products


def run(text: str, **kwargs):
    return import_products(io.StringIO(text), **kwargs)


def test_error_in_two_line_record_reports_its_first_line():
    text = (
        "sku,name,price\n"
        'LAMP-7,"Desk lamp\n(warm white)",12.5x\n'
        "CUP-1,Cup,3.00\n"
    )
    result = run(text)
    assert [p.sku for p in result.products] == ["CUP-1"]
    assert [(e.line, e.field) for e in result.errors] == [(2, "price")]


def test_error_in_record_spanning_three_lines_reports_its_first_line():
    text = (
        "sku,name,price\n"
        "CUP-1,Cup,3.00\n"
        'RUG-9,"Hall runner\n80 x 240 cm\nhand-woven",-4.00\n'
        "MAT-2,Mat,8.00\n"
    )
    result = run(text)
    assert [str(e) for e in result.errors] == ["line 3: price: price cannot be negative"]
    assert [p.sku for p in result.products] == ["CUP-1", "MAT-2"]


def test_duplicate_of_a_multiline_record_names_the_line_it_started_on():
    text = (
        "sku,name,price\n"
        'LAMP-7,"Desk lamp\n(warm white)\nwith dimmer",19.00\n'
        "LAMP-7,Desk lamp,19.00\n"
    )
    result = run(text)
    assert len(result.products) == 1
    assert [str(e) for e in result.errors] == ["line 5: sku: duplicate sku LAMP-7 (first seen on line 2)"]


def test_wrong_field_count_in_multiline_record():
    text = (
        "sku,name,price\n"
        'VASE-3,"Tall vase\nceramic"\n'
    )
    result = run(text)
    assert [str(e) for e in result.errors] == ["line 2: expected 3 fields, got 2"]


def test_multiline_record_after_blank_lines():
    text = (
        "sku,name,price\n"
        "\n"
        "\n"
        'POT-4,"Plant pot\nterracotta",\n'
    )
    result = run(text)
    assert [(e.line, e.field) for e in result.errors] == [(4, "price")]


def test_crlf_file_with_multiline_cell(tmp_path):
    path = tmp_path / "export.csv"
    content = (
        "sku,name,price,weight_grams\r\n"
        'TRAY-5,"Serving tray\r\noak",14.00,1.5\r\n'
        "BOARD-6,Cutting board,22.00,900\r\n"
    )
    path.write_bytes(content.encode("utf-8-sig"))
    result = load_products(path)
    assert [(e.line, e.field) for e in result.errors] == [(2, "weight_grams")]
    assert [p.sku for p in result.products] == ["BOARD-6"]


def test_later_rows_and_duplicates_after_a_multiline_record():
    text = (
        "sku,name,price\n"
        'LAMP-7,"Desk lamp\n(warm white)",19.00\n'
        "CUP-1,,3.00\n"
        "LAMP-7,Lamp again,19.00\n"
    )
    result = run(text)
    assert [str(e) for e in result.errors] == [
        "line 4: name: name is empty",
        "line 5: sku: duplicate sku LAMP-7 (first seen on line 2)",
    ]


# -- guards: behaviour that was already right must stay right ---------------


def test_valid_multiline_names_are_imported_intact():
    result = run('sku,name,price\nLAMP-7,"Desk lamp\n(warm white)",19.00\n')
    assert result.ok
    assert result.products[0].name == "Desk lamp\n(warm white)"


def test_single_line_rows_after_a_multiline_record():
    text = (
        "sku,name,price\n"
        'LAMP-7,"Desk lamp\n(warm white)",19.00\n'
        "CUP-1,Cup,abc\n"
        "\n"
        "BOWL-2,,4.00\n"
    )
    result = run(text)
    assert [(e.line, e.field) for e in result.errors] == [(4, "price"), (6, "name")]
