from rashomon.text import cluster, containment, jaccard, slug, split_identifier, stem, tokens


def test_stem_handles_plurals_and_short_words():
    assert stem("invoices") == stem("invoice") == "invoice"
    assert stem("rows") == "row"
    assert stem("filtered") == "filter"
    assert stem("status") == "status"
    assert stem("classes") == "class"


def test_split_identifier_camel_snake_and_paths():
    assert split_identifier("InvoiceTable") == ["Invoice", "Table"]
    assert split_identifier("filter_invoices") == ["filter", "invoices"]
    assert split_identifier("/invoices/{invoice_id}") == ["invoices", "invoice", "id"]


def test_tokens_keep_meaningful_small_words():
    assert tokens("all rows") == {"all", "row"}
    assert "the" not in tokens("the filtered view")


def test_jaccard_and_containment():
    assert jaccard(frozenset(), frozenset()) == 1.0
    assert jaccard(tokens("export scope"), tokens("scope of the export")) == 1.0
    assert containment(tokens("amount format"), tokens("amounts should be formatted")) == 1.0


def test_cluster_is_order_stable_and_groups_paraphrases():
    ids = cluster(["export scope", "amount format", "scope of the export", "Export scope"], 0.5)
    assert ids == [0, 1, 0, 0]


def test_slug():
    assert slug("Export scope!") == "export-scope"
    assert slug("") == "item"
