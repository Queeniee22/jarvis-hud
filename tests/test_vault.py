from jarvis.services.vault import build_graph

def test_build_graph_nodes_and_links():
    files = ["A.md", "B.md", "C.md"]
    links = {"A.md": ["B.md"], "B.md": ["C.md"], "C.md": []}
    g = build_graph(files, links)
    assert g["type"] == "graph"
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"A.md", "B.md", "C.md"}
    assert {"s": "A.md", "t": "B.md"} in g["links"]
    assert {"s": "B.md", "t": "C.md"} in g["links"]

def test_build_graph_resolves_wikilink_by_basename():
    files = ["00 Index/Jarvis Home.md", "01 Preferences/About Mackenzie.md"]
    links = {"00 Index/Jarvis Home.md": ["About Mackenzie"], "01 Preferences/About Mackenzie.md": []}
    g = build_graph(files, links)
    assert {"s": "00 Index/Jarvis Home.md", "t": "01 Preferences/About Mackenzie.md"} in g["links"]
