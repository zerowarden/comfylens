from typing import Any

from conftest import load_golden
from graph_builder import GraphBuilder, basic_txt2img

from comfylens.config import Config
from comfylens.extract.cleanup import (
    Cleanup,
    clean_prompt,
    clean_workflow,
    mirrored,
    plan_cleanup,
)
from comfylens.extract.pipeline import extract_outcome

POWER = "Power Lora Loader (rgthree)"


def plan(prompt: dict[str, Any], config: Config) -> Cleanup:
    out = extract_outcome(prompt, config)
    assert out.graph is not None and out.reach is not None
    return plan_cleanup(out.graph, out.reach)


def workflow_of(prompt: dict[str, Any]) -> dict[str, Any]:
    """A format 0.4 UI workflow with the prompt's nodes and links. Power Lora Loader entries
    become widget values after rgthree's header widget, as rgthree saves them."""
    links = [
        [n, int(src), slot, int(dst), 0, "*"]
        for n, (dst, src, slot) in enumerate(
            (
                (dst, value[0], value[1])
                for dst, node in prompt.items()
                for value in node["inputs"].values()
                if isinstance(value, list)
            ),
            start=1,
        )
    ]

    def node(node_id: str, value: dict[str, Any]) -> dict[str, Any]:
        entries = [v for v in value["inputs"].values() if isinstance(v, dict)]
        return {
            "id": int(node_id),
            "type": value["class_type"],
            "mode": 0,
            "inputs": [
                {"name": "in", "link": link[0]} for link in links if link[3] == int(node_id)
            ],
            "outputs": [
                {"name": "out", "links": [link[0] for link in links if link[1] == int(node_id)]}
            ],
            "widgets_values": [{}, {"type": "PowerLoraLoaderHeaderWidget"}, *entries, {}, ""]
            if entries
            else [],
        }

    nodes = [node(node_id, value) for node_id, value in prompt.items()]
    return {"version": 0.4, "nodes": nodes, "links": links, "extra": {}}


def with_loras(*loras: tuple[str, str, str | None]) -> GraphBuilder:
    """basic_txt2img plus LoRA nodes (id, class, model source)."""
    g = basic_txt2img()
    for node_id, class_type, source in loras:
        model = {"model": (source, 0)} if source else {}
        inputs = {"lora_name": f"{node_id}.safetensors", "strength_model": 1.0, **model}
        g.node(node_id, class_type, inputs=inputs)
    return g


def test_the_golden_unused_lora_leaves_both_documents(config: Config):
    prompt = load_golden("sample_qwen21.prompt.json")
    workflow = load_golden("sample_qwen21.workflow.json")
    cleanup = mirrored(workflow, plan(prompt, config))
    assert cleanup == Cleanup({"25": "LoraLoaderModelOnly"}, {})

    assert set(clean_prompt(prompt, cleanup)) == set(prompt) - {"25"}
    cleaned = clean_workflow(workflow, cleanup)
    assert 25 not in {n["id"] for n in cleaned["nodes"]}
    assert 65 not in {link[0] for link in cleaned["links"]}  # 29 -> 25
    (node_29,) = (n for n in cleaned["nodes"] if n["id"] == 29)
    assert node_29["outputs"][0]["links"] == [66]
    assert len(cleaned["links"]) == len(workflow["links"]) - 1
    # Cleaning again changes nothing.
    assert not mirrored(cleaned, plan(clean_prompt(prompt, cleanup), config))


def test_only_dangling_unreachable_loras_go(config: Config):
    g = with_loras(
        ("20", "LoraLoaderModelOnly", "1"),  # feeds 21 only
        ("21", "LoraLoaderModelOnly", "20"),  # feeds nothing
        ("22", "LoraLoaderModelOnly", "1"),  # feeds a node that stays
        ("24", "LoraLoaderModelOnly", None),  # loads nothing, feeds nothing
    )
    g.node("23", "ModelSamplingFlux", max_shift=1.15, model=("22", 0))
    g.node("30", "LoraLoaderModelOnly", lora_name="used.safetensors", strength_model=0.8,
           model=("1", 0))  # fmt: skip
    g.prompt["7"]["inputs"]["model"] = ["30", 0]  # on the sampler's chain
    assert plan(g.prompt, config).nodes == {
        "20": "LoraLoaderModelOnly",
        "21": "LoraLoaderModelOnly",
        "24": "LoraLoaderModelOnly",
    }


def test_switched_off_power_entries_go_from_both_documents(config: Config):
    off = {"on": False, "lora": "old.safetensors", "strength": 1.0}
    on = {"on": True, "lora": "fox.safetensors", "strength": 0.8}
    g = basic_txt2img()
    g.node("20", POWER, model=("1", 0), inputs={"lora_1": off, "lora_2": on, "lora_3": dict(off)})
    g.prompt["7"]["inputs"]["model"] = ["20", 0]
    workflow = workflow_of(g.prompt)
    cleanup = mirrored(workflow, plan(g.prompt, config))
    assert cleanup.nodes == {}
    assert cleanup.entries == {"20": {"lora_1": off, "lora_3": off}}

    assert clean_prompt(g.prompt, cleanup)["20"]["inputs"] == {"model": ["1", 0], "lora_2": on}
    (node,) = (n for n in clean_workflow(workflow, cleanup)["nodes"] if n["id"] == 20)
    assert node["widgets_values"] == [{}, {"type": "PowerLoraLoaderHeaderWidget"}, on, {}, ""]


def test_what_the_workflow_does_not_hold_stays_in_both(config: Config):
    g = with_loras(("20", "LoraLoaderModelOnly", "1"), ("21", "LoraLoaderModelOnly", "1"))
    workflow = workflow_of(g.prompt)
    workflow["nodes"] = [n for n in workflow["nodes"] if n["id"] != 21]  # e.g. in a subgraph
    workflow["nodes"][-1]["type"] = "Renamed"  # node 20, of another type in the workflow
    assert mirrored(workflow, plan(g.prompt, config)) == Cleanup({}, {})


def test_object_links_and_native_reroutes(config: Config):
    g = with_loras(("20", "LoraLoaderModelOnly", "1"))
    workflow = workflow_of(g.prompt)
    (gone,) = (link[0] for link in workflow["links"] if link[3] == 20)
    workflow["version"] = 1
    workflow["links"] = [
        {"id": i, "origin_id": o, "origin_slot": os, "target_id": t, "target_slot": ts}
        for i, o, os, t, ts, _ in workflow["links"]
    ]
    workflow["extra"] = {
        "reroutes": [{"id": 1, "linkIds": [gone, 1]}],
        "linkExtensions": [{"id": gone, "parentId": 1}, {"id": 1, "parentId": 1}],
    }
    cleaned = clean_workflow(workflow, mirrored(workflow, plan(g.prompt, config)))
    assert gone not in {link["id"] for link in cleaned["links"]}
    assert cleaned["extra"] == {
        "reroutes": [{"id": 1, "linkIds": [1]}],
        "linkExtensions": [{"id": 1, "parentId": 1}],
    }
    (unet,) = (n for n in cleaned["nodes"] if n["id"] == 1)
    assert gone not in unet["outputs"][0]["links"]
