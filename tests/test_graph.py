import re

import pytest
from graph_builder import GraphBuilder, basic_txt2img

from comfylens.extract.pipeline import extract_outcome
from comfylens.extract.registry import SAMPLER_CLASSES, SWITCHES
from comfylens.extract.switches import inactive_inputs
from comfylens.graph.model import Link, parse_graph
from comfylens.graph.reachability import analyze_reachability
from comfylens.warn import Code

OUTPUTS = frozenset({"SaveImage", "PreviewImage"})
OUTPUT_NAMES = re.compile(r"(?i)(save|preview)")


def reach(g: GraphBuilder):
    graph = parse_graph(g.prompt)
    return analyze_reachability(
        graph, OUTPUTS, OUTPUT_NAMES, SAMPLER_CLASSES, inactive_inputs(graph, SWITCHES)
    )


@pytest.mark.parametrize(
    "value,is_link",
    [
        (["1", 0], True),
        (["1", 2], True),
        (["99", 0], False),  # not a node in this graph
        ([1, 0], False),  # id must be a string
        (["1", "0"], False),  # slot must be an int
        (["1", True], False),  # bool is not a slot
        (["1", 0, 0], False),
        (["1"], False),
        ("1", False),
    ],
)
def test_link_detection(value, is_link):
    graph = parse_graph(
        {
            "1": {"class_type": "A", "inputs": {}},
            "2": {"class_type": "B", "inputs": {"x": value}},
        }
    )
    assert isinstance(graph.nodes["2"].inputs["x"], Link) is is_link
    assert ("1" in graph.consumers) is is_link


def test_parse_keeps_meta_extra_dicts_and_opaque_ids():
    graph = parse_graph(
        {
            "12:5": {
                "class_type": "LoadImage",
                "inputs": {"image": "a.png", "lora_1": {"on": True}},
                "_meta": {"title": "Load"},
                "is_changed": ["abc"],
            },
            "7": {"class_type": "X", "inputs": {"image": ["12:5", 1]}},
            "junk": 5,
        }
    )
    node = graph.nodes["12:5"]
    assert node.title == "Load"
    assert node.extra == {"is_changed": ["abc"]}
    assert node.inputs["lora_1"] == {"on": True}
    assert graph.nodes["7"].inputs["image"] == Link("12:5", 1)
    assert graph.consumers == {"12:5": [("7", "image", 1)]}
    assert "junk" not in graph.nodes


def test_dead_branch_and_dangling_node_are_unreachable():
    g = basic_txt2img()
    g.node("20", "LoraLoaderModelOnly", lora_name="x.safetensors", model=("1", 0))
    g.node("21", "VAEEncodeForInpaint", grow_mask_by=6)
    r = reach(g)
    assert r.outputs == ["9"]
    assert r.reachable == {"1", "2", "3", "4", "5", "6", "7", "8", "9"}
    assert r.warnings == []


def test_topological_order_breaks_ties_by_id_string():
    r = reach(basic_txt2img())
    # Roots 1, 2, 3, 6 are ready together; "4" < "5" < "6" as strings.
    assert r.order == ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
    assert r.rank["7"] == 6


def test_output_name_regex_needs_no_consumers():
    g = basic_txt2img()
    g.node("9", "Image Saver Custom", images=("8", 0))  # unknown class, matches by name
    g.node("10", "PreviewBridge", images=("7", 0))  # matches by name but is consumed
    g.node("11", "Consumer", x=("10", 0))
    assert reach(g).outputs == ["9"]


def test_no_output_node_falls_back_to_samplers():
    g = basic_txt2img()
    del g.prompt["9"]
    del g.prompt["8"]
    r = reach(g)
    assert r.outputs == []
    assert "7" in r.reachable and "3" not in r.reachable
    assert [w.code for w in r.warnings] == [Code.NO_OUTPUT_NODE]


def test_extract_outcome_reports_a_graph_cycle(config):
    g = basic_txt2img()
    g.node("4", "CLIPTextEncode", text="loop", clip=("2", 0), extra_in=("7", 0))
    out = extract_outcome(g.prompt, config)
    assert out.status == "error" and out.error is not None
    assert out.error.startswith("GRAPH_CYCLE")
    assert [w.code for w in out.warnings] == [Code.GRAPH_CYCLE]


def test_multiple_output_branches():
    g = basic_txt2img()
    # SaveImage shows the first pass and a preview shows a second pass.
    g.node(
        "17",
        "KSampler",
        seed=1,
        steps=10,
        cfg=3.5,
        sampler_name="euler",
        scheduler="simple",
        denoise=0.5,
        model=("1", 0),
        positive=("4", 0),
        negative=("5", 0),
        latent_image=("7", 0),
    )
    g.node("18", "VAEDecode", samples=("17", 0), vae=("3", 0))
    g.node("19", "PreviewImage", images=("18", 0))
    assert [w.code for w in reach(g).warnings] == [Code.MULTIPLE_OUTPUT_BRANCHES]


def test_two_outputs_of_one_sampler_is_one_branch():
    g = basic_txt2img()
    g.node("19", "PreviewImage", images=("8", 0))
    assert reach(g).warnings == []


def two_pass(switch_class: str, condition, *, condition_input: str = "switch") -> GraphBuilder:
    """A first pass always runs; a lazy switch picks it or a second pass for the output."""
    g = basic_txt2img()
    g.node(
        "17",
        "KSampler",
        seed=1,
        steps=10,
        cfg=1.0,
        sampler_name="euler",
        scheduler="simple",
        denoise=0.5,
        model=("1", 0),
        positive=("4", 0),
        negative=("5", 0),
        latent_image=("7", 0),
    )
    g.node("18", "VAEDecode", samples=("17", 0), vae=("3", 0))
    g.node(
        "20",
        switch_class,
        inputs={condition_input: condition},
        on_true=("18", 0),
        on_false=("8", 0),
    )
    g.node("9", "SaveImage", images=("20", 0))
    return g


@pytest.mark.parametrize(
    "switch_class,condition_input", [("ComfySwitchNode", "switch"), ("easy ifElse", "boolean")]
)
def test_constant_switch_prunes_the_branch_that_did_not_run(switch_class, condition_input):
    g = two_pass(switch_class, False, condition_input=condition_input)
    r = reach(g)
    assert "17" not in r.reachable and "18" not in r.reachable
    assert "8" in r.reachable

    g = two_pass(switch_class, True, condition_input=condition_input)
    r = reach(g)
    assert {"17", "18", "7"} <= r.reachable  # the second pass needs the first one's latent
    assert "8" not in r.reachable  # but not its decoded image


def test_switch_condition_through_a_primitive_boolean():
    g = two_pass("ComfySwitchNode", ["30", 0])
    g.node("30", "PrimitiveBoolean", value=False)
    r = reach(g)
    assert "30" in r.reachable and "17" not in r.reachable


def test_computed_switch_condition_keeps_both_branches():
    g = two_pass("ComfySwitchNode", ["30", 0])
    g.node("30", "CompareNumbers", a=1, b=2, op="<")
    assert {"17", "18", "8"} <= reach(g).reachable


def test_a_bool_literal_on_a_computed_node_is_not_a_constant_condition():
    # StringContains has exactly one bool input (case_sensitive); it does not make the
    # switch constant, because its output is computed at run time.
    g = two_pass("ComfySwitchNode", ["30", 0])
    g.node("30", "StringContains", text=("4", 0), substring="fox", case_sensitive=True)
    assert {"17", "18", "8"} <= reach(g).reachable


def test_switch_is_ordered_after_the_node_it_selects():
    g = GraphBuilder()
    g.node("1", "UNETLoader", unet_name="flux1-dev.safetensors")
    g.node(
        "70", "LoraLoaderModelOnly", lora_name="x.safetensors", strength_model=1.0, model=("1", 0)
    )
    g.node("2", "ComfySwitchNode", switch=True, on_true=("70", 0), on_false=("1", 0))
    g.node("9", "SaveImage", images=("2", 0))
    order = reach(g).order
    assert order.index("70") < order.index("2")


def test_constant_switch_does_not_promote_the_stage_it_feeds():
    # A constant switch feeds a parallel refine pass; the base pass still comes first.
    g = basic_txt2img()
    g.node("42", "EmptyLatentImage", width=512, height=512, batch_size=1)
    g.node(
        "70", "LoraLoaderModelOnly", lora_name="x.safetensors", strength_model=1.0, model=("1", 0)
    )
    g.node("10", "ComfySwitchNode", switch=True, on_true=("70", 0), on_false=("1", 0))
    g.node(
        "0",
        "KSampler",
        seed=1,
        steps=20,
        cfg=3.5,
        sampler_name="euler",
        scheduler="simple",
        denoise=0.4,
        model=("10", 0),
        positive=("4", 0),
        negative=("5", 0),
        latent_image=("42", 0),
    )
    g.node("18", "VAEDecode", samples=("0", 0), vae=("3", 0))
    g.node("19", "SaveImage", images=("18", 0), filename_prefix="refine")
    order = reach(g).order
    assert order.index("7") < order.index("0")  # the seed-42 base pass is primary


def test_soft_switch_falls_back_to_the_connected_input():
    g = two_pass("ComfySoftSwitchNode", True)
    del g.prompt["20"]["inputs"]["on_true"]
    r = reach(g)
    assert "8" in r.reachable and "17" not in r.reachable
