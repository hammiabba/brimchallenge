from app.extraction.vendor_match import resolve
from app.shared.schemas import BankDetails, MatchMethod, VendorOnInvoice


def test_gst_beats_lookalike_name(repo):
    # EM-026: "Harlow and Stern LLP" from harlowandstern-llp.example. GST is V052's, not V026's.
    inv = VendorOnInvoice(name_on_invoice="Harlow and Stern LLP", gst_number="503486760RT0001")
    out, _ = resolve(inv, "ar@harlowandstern-llp.example", repo)
    assert (out.vendor_id, out.match_method, out.match_score) == ("V052", MatchMethod.GST_NUMBER, 1.0)


def test_buyer_gst_is_ignored(repo):
    inv = VendorOnInvoice(name_on_invoice="Nobody Inc", gst_number="100000001RT0001")
    out, _ = resolve(inv, None, repo)
    assert out.vendor_id is None


def test_bank_account_match(repo):
    inv = VendorOnInvoice(name_on_invoice="Harlow & Stern",
                          bank=BankDetails(institution="010", transit="40238", account="593014216"))
    out, _ = resolve(inv, None, repo)
    assert (out.vendor_id, out.match_method) == ("V052", MatchMethod.BANK_ACCOUNT)


def test_domain_with_duplicate_record_prefers_active_and_warns(repo):
    # greatlakes.example is shared by V002 (active) and V053 (on_hold duplicate record)
    inv = VendorOnInvoice(name_on_invoice="Great Lakes Carriers Inc.")
    out, warnings = resolve(inv, "ar@greatlakes.example", repo)
    assert (out.vendor_id, out.match_method) == ("V002", MatchMethod.EMAIL_DOMAIN)
    assert any("V053" in w for w in warnings)


def test_domain_with_conflicting_gst_is_downgraded(repo):
    inv = VendorOnInvoice(name_on_invoice="Polar Freight Lines Ltd.", gst_number="999999999RT0001")
    out, warnings = resolve(inv, "ar@polarfreight.example", repo)
    assert out.match_method == MatchMethod.EMAIL_DOMAIN
    assert out.match_score == 0.5
    assert any("differs" in w for w in warnings)


def test_fuzzy_name_exact_record_wins_over_lookalike(repo):
    inv = VendorOnInvoice(name_on_invoice="Harlow & Stern LLP")
    out, _ = resolve(inv, None, repo)
    assert (out.vendor_id, out.match_method) == ("V026", MatchMethod.FUZZY_NAME)


def test_fuzzy_name_rejected_when_gst_contradicts(repo):
    inv = VendorOnInvoice(name_on_invoice="Harlow & Stern LLP", gst_number="111111111RT0001")
    out, warnings = resolve(inv, None, repo)
    assert out.vendor_id is None
    assert any("lookalike" in w for w in warnings)


def test_unknown_vendor(repo):
    # Invoice 4443.pdf: Blue Heron Couriers is not in the master
    inv = VendorOnInvoice(name_on_invoice="Blue Heron Couriers", gst_number="324978405RT0001",
                          bank=BankDetails(institution="004", transit="39446", account="38053633"))
    out, _ = resolve(inv, "ar@blueheron.example", repo)
    assert (out.vendor_id, out.match_method, out.match_score) == (None, MatchMethod.NONE, 0.0)
