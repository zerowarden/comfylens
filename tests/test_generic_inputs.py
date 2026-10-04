from graph_builder import GraphBuilder

from comfylens.extract.inputs import MAX_STR_CHARS


def test_generic_layer(config):
    g = GraphBuilder()
    g.node("1", "UNETLoader", unet_name="m.safetensors")
    g.node(
        "2",
        "Power Lora Loader (rgthree)",
        inputs={"lora_1": {"on": True, "lora": "a.safetensors", "strength": 0.5, "x": [1, 2]}},
        model=("1", 0),
    )
    g.node(
        "3",
        "KSampler",
        seed=1,
        cfg=2.5,
        add_noise=True,
        sigmas_override=None,
        long=("y" * (MAX_STR_CHARS + 10)),
        empty={},
        model=("2", 0),
    )
    g.node("4", "SaveImage", images=("3", 0))
    g.node("5", "Note", text="unreachable")
    found = {(i.node_id, i.input_name): i for i in g.extract(config).generic_inputs}

    assert ("2", "model") not in found  # links are skipped
    assert (found["2", "lora_1.on"].kind, found["2", "lora_1.on"].value) == ("bool", True)
    assert (found["2", "lora_1.lora"].kind, found["2", "lora_1.strength"].kind) == ("str", "num")
    assert (found["2", "lora_1.x"].kind, found["2", "lora_1.x"].value) == ("json", "[1, 2]")
    assert (found["3", "seed"].kind, found["3", "seed"].value) == ("num", 1)
    assert found["3", "sigmas_override"].value == "null"
    assert found["3", "empty"].value == "{}"
    assert len(str(found["3", "long"].value)) == MAX_STR_CHARS
    assert found["3", "cfg"].reachable
    assert not found["5", "text"].reachable
