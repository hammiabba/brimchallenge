"""Guards for the schema sent to the LLM API, plus the wire → internal conversion.

The structured-outputs API rejects a schema with more than 16 union-typed parameters
(HTTP 400 "too many parameters with union types"). The fake-client tests never send a
schema, so this file checks it directly, offline.
"""
from pydantic import TypeAdapter

from app.extraction.llm_parser import RawInvoice, RawLine, RawTax, WireInvoice, WireLine, WireTax, to_raw

API_UNION_PARAM_LIMIT = 16  # documented structured-outputs limit


def _is_union(prop: dict) -> bool:
    return "anyOf" in prop or "oneOf" in prop or isinstance(prop.get("type"), list)


def count_union_params(schema: dict) -> int:
    """Count union-typed properties in the root object and every $defs entry (recursing into inline objects)."""
    def walk(node: dict) -> int:
        n = 0
        for prop in node.get("properties", {}).values():
            n += _is_union(prop) + walk(prop) + walk(prop.get("items", {}))
        return n

    return walk(schema) + sum(walk(d) for d in schema.get("$defs", {}).values())


def sent_schema(model) -> dict:
    """The schema exactly as the SDK sends it (messages.parse applies the same transform)."""
    from anthropic.lib._parse._transform import transform_schema

    return transform_schema(TypeAdapter(model).json_schema())


def test_wire_schema_has_no_unions():
    for schema in (WireInvoice.model_json_schema(), sent_schema(WireInvoice)):
        n = count_union_params(schema)
        assert n == 0
        assert n <= API_UNION_PARAM_LIMIT


def test_guard_catches_the_old_internal_model():
    # RawInvoice was what we used to send; it is over the limit, which caused the 400s.
    assert count_union_params(RawInvoice.model_json_schema()) > API_UNION_PARAM_LIMIT


# ---------------------------------------------------------------- to_raw

def wire(**overrides) -> WireInvoice:
    base = dict(
        document_type="invoice", vendor_name="Laurentian Logistics Inc.", vendor_address="", vendor_gst_number="",
        vendor_qst_number="", vendor_email="", invoice_number="FA-002399", invoice_date="2026-10-25", due_date="",
        payment_terms="", currency="", bill_to_name="", bill_to_address="", ship_to_address="", po_number="",
        po_field_present=False, contract_reference="", lines=[], subtotal="", taxes=[], total="",
        bank_institution="", bank_transit="", bank_account="",
    )
    base.update(overrides)
    return WireInvoice(**base)


def test_empty_and_whitespace_become_none():
    raw = to_raw(wire(due_date="", currency="   ", po_number="\t"))
    assert raw.due_date is None and raw.currency is None and raw.po_number is None


def test_real_values_kept_exactly():
    raw = to_raw(wire(total="4 362,67 $", invoice_number=" FA-002399 "))
    assert raw.total == "4 362,67 $"
    assert raw.invoice_number == "FA-002399"  # surrounding whitespace is not part of the value


def test_empty_lists_stay_empty():
    raw = to_raw(wire())
    assert raw.lines == [] and raw.taxes == []


def test_nested_lines_and_taxes_converted():
    raw = to_raw(wire(
        lines=[WireLine(description="Fuel surcharge", quantity="", unit_price=" ", amount="454,17 $",
                        line_type="services")],
        taxes=[WireTax(label="TPS (5 %)", rate=" ", amount="218,13 $")],
    ))
    assert raw.lines == [RawLine(description="Fuel surcharge", quantity=None, unit_price=None,
                                 amount="454,17 $", line_type="services")]
    assert raw.taxes == [RawTax(label="TPS (5 %)", rate=None, amount="218,13 $")]


def test_wire_and_raw_models_have_the_same_fields():
    # Adding a field to one model but not the other would silently drop it.
    for w, r in ((WireInvoice, RawInvoice), (WireLine, RawLine), (WireTax, RawTax)):
        assert set(w.model_fields) == set(r.model_fields)
