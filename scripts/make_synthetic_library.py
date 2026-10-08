"""Write a synthetic ComfyUI library for benchmarking and manual testing.

    uv run python scripts/make_synthetic_library.py 100000 /tmp/synthetic-library

Writes N small PNGs (64x64) with varied API prompts: several model families, LoRA stacks
(including Power Lora Loader and unused LoRA nodes), KSampler, SamplerCustomAdvanced and
two-stage graphs, prompts drawn from a word list with a shared template sentence on 60% of
them, batches of 1-4 images sharing one prompt, and mtimes spread over the last 90 days.
About 1% of files are byte-identical copies. Graphs are deterministic for a given --seed.
"""

import argparse
import io
import json
import os
import random
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from PIL import Image
from PIL.PngImagePlugin import PngInfo

WORDS = """
portrait landscape city forest river mountain castle robot dragon cat dog fox owl knight
witch astronaut samurai pirate dancer musician chef soldier queen king child elder neon
sunset sunrise night rain snow fog storm desert ocean beach island village street market
cafe library temple garden bridge tower station train ship airship spaceship cyberpunk
steampunk baroque minimal surreal vintage cinematic dramatic soft warm cold golden silver
crimson azure emerald violet amber ivory obsidian marble glass velvet silk leather wool
lantern candle mirror window doorway staircase balcony rooftop alley courtyard meadow
""".split()  # noqa: SIM905 (a word list reads better as text)
STYLES = [
    "highly detailed",
    "sharp focus",
    "film grain",
    "volumetric light",
    "shallow depth of field",
    "35mm photograph",
    "oil painting",
    "watercolor",
    "studio lighting",
    "golden hour",
]
TEMPLATE = "Preserve the subject's identity, pose and composition from the reference image."
NEGATIVES = ["blurry, low quality", "plastic, blur, low quality, text", "", "watermark, jpeg"]

FAMILIES = [  # name, weight
    ("qwen21", 0.40),
    ("qwen", 0.10),
    ("flux", 0.15),
    ("krea", 0.05),  # FLUX.1 Krea [dev]
    ("krea2", 0.20),  # Krea 2, shaped like ComfyUI's "Text to Image (Krea-2 Turbo)" template
    ("krea2-api", 0.05),  # Krea 2 through the hosted Krea2ImageNode
    ("ideogram", 0.05),
]
LORAS = {
    "qwen21": [f"qwen2.1-style{i:02d}" for i in range(12)] + ["qwen2.1-mystyle_000004000"],
    "qwen": [f"qwen-detail{i:02d}" for i in range(6)],
    "flux": [f"flux-lora{i:02d}" for i in range(10)] + ["flux-styleV2_000012000"],
    "krea": [f"krea-look{i:02d}" for i in range(5)],
    "krea2": ["krea2_darkbrush", "krea2_inkwash", "krea2_film_still", "krea2_pastel"],
}
KREA2_SYSTEM = "You are an expert prompt engineer for text-to-image models. Expand the idea."
KREA2_STYLES = ["muted minimalist sketch style", "ink wash", "35mm film still", "soft pastel"]
SAMPLERS = ["euler", "euler_ancestral", "res_multistep", "res_2m", "dpmpp_2m"]
SCHEDULERS = ["simple", "beta", "karras", "normal"]
DAY = 86_400


def prompt_text(rng: random.Random) -> str:
    subject = " ".join(rng.sample(WORDS, rng.randint(3, 8)))
    styles = ", ".join(rng.sample(STYLES, rng.randint(1, 4)))
    text = f"A {subject}, {styles}."
    if rng.random() < 0.6:
        text = f"{TEMPLATE}\n\n{text}"
    return text


def lora_chain(
    g: dict[str, Any], rng: random.Random, family: str, model: list[Any], clip: list[Any] | None
) -> list[Any]:
    """Insert 0-3 LoRAs after `model`; sometimes a Power Lora Loader or an unused LoRA."""
    pool = LORAS[family]
    for i in range(rng.choice([0, 1, 1, 2, 2, 3])):
        node_id = str(40 + i)
        strength = rng.choice([0.6, 0.8, 0.9, 1.0, 1.0, 1.13])
        g[node_id] = node(
            "LoraLoaderModelOnly",
            lora_name=f"{rng.choice(pool)}.safetensors",
            strength_model=strength,
            model=model,
        )
        model = [node_id, 0]
    if rng.random() < 0.15:
        entries = {
            f"lora_{k}": {
                "on": k != 2,
                "lora": f"{rng.choice(pool)}.safetensors",
                "strength": rng.choice([0.5, 0.75, 1.0]),
            }
            for k in range(1, rng.randint(2, 4))
        }
        g["50"] = node(
            "Power Lora Loader (rgthree)",
            PowerLoraLoaderHeaderWidget={"type": "PowerLoraLoaderHeaderWidget"},
            **entries,
            model=model,
            clip=clip,
        )
        model = ["50", 0]
    if rng.random() < 0.3:  # loaded but connected to nothing
        g["60"] = node(
            "LoraLoaderModelOnly",
            lora_name=f"{rng.choice(pool)}.safetensors",
            strength_model=0.97,
            model=model,
        )
    return model


def node(class_type: str, **inputs: Any) -> dict[str, Any]:
    return {
        "inputs": {k: v for k, v in inputs.items() if v is not None},
        "class_type": class_type,
        "_meta": {"title": class_type},
    }


def krea2_turbo(rng: random.Random, positive: str) -> dict[str, Any]:
    """Subgraph 30 of the Krea-2 Turbo template: switches pick the LoRA, the style suffix and
    an optional LLM rewrite of the prompt (TextGenerate)."""
    s = "30:"
    lora, enhance = rng.random() < 0.5, rng.random() < 0.3
    g = {
        "49": node("ResolutionSelector", aspect_ratio="1:1 (Square)", megapixels=1, multiple=8),
        s + "10": node(
            "UNETLoader",
            unet_name=rng.choice(
                ["krea2_turbo_fp8_scaled.safetensors", "krea2_turbo_int8_convrot.safetensors"]
            ),
            weight_dtype="default",
        ),
        s + "11": node(
            "CLIPLoader",
            clip_name="qwen3vl_4b_fp8_scaled.safetensors",
            type="krea2",
            device="default",
        ),
        s + "12": node("VAELoader", vae_name="qwen_image_vae.safetensors"),
        s + "15": node(
            "LoraLoaderModelOnly",
            lora_name=f"{rng.choice(LORAS['krea2'])}.safetensors",
            strength_model=rng.choice([0.6, 0.8, 0.8, 1.0]),
            model=[s + "10", 0],
        ),
        s + "23": node("PrimitiveBoolean", value=lora),
        s + "24": node("PrimitiveBoolean", value=enhance),
        s + "22": node(
            "ComfySwitchNode", switch=[s + "23", 0], on_false=[s + "10", 0], on_true=[s + "15", 0]
        ),
        s + "18": node("PrimitiveStringMultiline", value=KREA2_SYSTEM),
        s + "19": node("PrimitiveStringMultiline", value=positive),
        s + "17": node(
            "StringConcatenate", string_a=[s + "18", 0], string_b=[s + "19", 0], delimiter=" "
        ),
        s + "16": node("TextGenerate", clip=[s + "11", 0], prompt=[s + "17", 0], max_length=512),
        s + "21": node(
            "ComfySwitchNode", switch=[s + "24", 0], on_false=[s + "19", 0], on_true=[s + "16", 0]
        ),
        s + "20": node("PreviewAny", source=[s + "21", 0]),
        s + "27": node(
            "StringConcatenate",
            string_a=[s + "20", 0],
            string_b=rng.choice(KREA2_STYLES),
            delimiter=", ",
        ),
        s + "28": node(
            "ComfySwitchNode", switch=[s + "23", 0], on_false=[s + "20", 0], on_true=[s + "27", 0]
        ),
        s + "6": node("CLIPTextEncode", text=[s + "28", 0], clip=[s + "11", 0]),
        s + "13": node("ConditioningZeroOut", conditioning=[s + "6", 0]),
        s + "5": node("EmptyLatentImage", width=["49", 0], height=["49", 1], batch_size=1),
        s + "3": node(
            "KSampler",
            seed=rng.randrange(2**50),
            steps=rng.choice([6, 8, 8, 8, 10]),
            cfg=1,
            sampler_name=rng.choice(["euler", "euler", "res_multistep"]),
            scheduler=rng.choice(["simple", "simple", "beta"]),
            denoise=1,
            model=[s + "22", 0],
            positive=[s + "6", 0],
            negative=[s + "13", 0],
            latent_image=[s + "5", 0],
        ),
        s + "8": node("VAEDecode", samples=[s + "3", 0], vae=[s + "12", 0]),
        "29": node("SaveImage", filename_prefix="Krea2_turbo", images=[s + "8", 0]),
    }
    return g


def api_prompt(rng: random.Random) -> dict[str, Any]:
    family = rng.choices([f for f, _ in FAMILIES], [w for _, w in FAMILIES])[0]
    positive, negative = prompt_text(rng), rng.choice(NEGATIVES)
    hosted = _HOSTED.get(family)
    return hosted(rng, positive) if hosted else sampled(rng, family, positive, negative)


def krea2_api(rng: random.Random, positive: str) -> dict[str, Any]:
    """Remote generation: the prompt is on the API node itself."""
    return {
        "1": node(
            "Krea2ImageNode",
            prompt=positive,
            seed=rng.randrange(2**31),
            **{"model": rng.choice(["Krea 2 Medium", "Krea 2 Large"]), "model.aspect_ratio": "1:1"},
        ),
        "2": node("SaveImage", images=["1", 0], filename_prefix="Krea2"),
    }


def ideogram(rng: random.Random, positive: str) -> dict[str, Any]:
    """A hosted API node: no sampler, no LoRAs."""
    return {
        "1": node(
            "IdeogramV4",
            prompt=positive,
            aspect_ratio=rng.choice(["1:1", "9:16", "16:9"]),
            seed=rng.randrange(2**32),
        ),
        "2": node("SaveImage", images=["1", 0], filename_prefix="ideogram"),
    }


_HOSTED = {"krea2": krea2_turbo, "krea2-api": krea2_api, "ideogram": ideogram}
_UNETS = {
    "qwen21": "qwen/qwen_image_2.1_int8_convrot.safetensors",
    "qwen": "qwen_image_fp8_e4m3fn.safetensors",
    "flux": "flux1-dev-fp8.safetensors",
    "krea": "flux1-krea-dev.safetensors",
}
_FLUX_LIKE = ("flux", "krea")

type Ref = list[Any]  # [node id, output slot]


def sampled(rng: random.Random, family: str, positive: str, negative: str) -> dict[str, Any]:
    """Loaders and LoRAs, conditioning, one or two sampling passes, decode and save."""
    g: dict[str, Any] = {}
    model = loaders(g, rng, family)
    pos, neg, latent = conditioning(g, rng, family, positive, negative)
    samples = sample(g, rng, family, model, pos, neg, latent)
    g["7"] = node("VAEDecode", samples=samples, vae=["3", 0])
    g["8"] = node("SaveImage", images=["7", 0], filename_prefix="ComfyUI")
    return g


def loaders(g: dict[str, Any], rng: random.Random, family: str) -> Ref:
    """The model, CLIP and VAE loaders and the LoRA chain; returns the model to sample with."""
    g["1"] = node("UNETLoader", unet_name=_UNETS[family], weight_dtype="default")
    clip_type = "flux" if family in _FLUX_LIKE else "qwen_image"
    g["2"] = (
        node(
            "DualCLIPLoader",
            clip_name1="clip_l.safetensors",
            clip_name2="t5xxl_fp8.safetensors",
            type=clip_type,
        )
        if family in _FLUX_LIKE
        else node("CLIPLoader", clip_name="qwen3vl_8b.safetensors", type=clip_type)
    )
    g["3"] = node("VAELoader", vae_name=f"{family}_vae.safetensors")
    model = lora_chain(g, rng, family, ["1", 0], ["2", 0])
    if family != "qwen":
        return model
    g["5"] = node("ModelSamplingAuraFlow", shift=rng.choice([2.5, 3.1, 3.1]), model=model)
    return ["5", 0]


def conditioning(
    g: dict[str, Any], rng: random.Random, family: str, positive: str, negative: str
) -> tuple[Ref, Ref, Ref]:
    """Positive and negative conditioning and the latent to start from."""
    width, height = rng.choice([(1024, 1024), (896, 1632), (1632, 896), (832, 1216)])
    if family == "qwen21":  # one node encodes both prompts and makes the latent
        g["9"] = node(
            "TextEncodeQwenImage21",
            prompt=positive,
            negative_prompt=negative,
            resolution=rng.choice([1024, 1216]),
            clip=["2", 0],
        )
        return ["9", 0], ["9", 1], ["9", 2]
    g["10"] = node("CLIPTextEncode", text=positive, clip=["2", 0])
    g["11"] = node("CLIPTextEncode", text=negative, clip=["2", 0])
    pos: Ref = ["10", 0]
    if family in _FLUX_LIKE:
        g["12"] = node("FluxGuidance", guidance=rng.choice([2.5, 3.5, 3.5, 4.0]), conditioning=pos)
        pos = ["12", 0]
    batch = rng.choice([1, 1, 2, 4])
    g["13"] = node("EmptySD3LatentImage", width=width, height=height, batch_size=batch)
    return pos, ["11", 0], ["13", 0]


def sample(
    g: dict[str, Any], rng: random.Random, family: str, model: Ref, pos: Ref, neg: Ref, latent: Ref
) -> Ref:
    """A KSampler, or now and then the custom-advanced nodes, plus sometimes a refining pass."""
    steps = rng.choice([8, 11, 20, 25, 25, 28, 30])
    cfg = 1.0 if family in _FLUX_LIKE else rng.choice([2.0, 2.5, 3.0, 4.0])
    sampler, scheduler = rng.choice(SAMPLERS), rng.choice(SCHEDULERS)
    seed = rng.randrange(2**50)
    if rng.random() < 0.15:
        g["20"] = node("RandomNoise", noise_seed=seed)
        g["21"] = node("CFGGuider", cfg=cfg, model=model, positive=pos, negative=neg)
        g["22"] = node("KSamplerSelect", sampler_name=sampler)
        g["23"] = node("BasicScheduler", scheduler=scheduler, steps=steps, denoise=1.0, model=model)
        g["6"] = node(
            "SamplerCustomAdvanced",
            noise=["20", 0],
            guider=["21", 0],
            sampler=["22", 0],
            sigmas=["23", 0],
            latent_image=latent,
        )
    else:
        denoise = rng.choice([1.0, 1.0, 0.97])
        g["6"] = node(
            "KSampler", seed=seed, steps=steps, cfg=cfg, sampler_name=sampler, scheduler=scheduler,
            denoise=denoise, model=model, positive=pos, negative=neg, latent_image=latent,
        )  # fmt: skip
    if rng.random() >= 0.1:
        return ["6", 0]
    # A second, refining pass.
    g["30"] = node(
        "LatentUpscaleBy", upscale_method="nearest-exact", scale_by=1.5, samples=["6", 0]
    )
    g["31"] = node(
        "KSampler", seed=seed + 1, steps=12, cfg=cfg, sampler_name=sampler, scheduler=scheduler,
        denoise=0.45, model=model, positive=pos, negative=neg, latent_image=["30", 0],
    )  # fmt: skip
    return ["31", 0]


def workflow_for(prompt: dict[str, Any]) -> dict[str, Any]:
    """A format 0.4 UI workflow with the prompt's top-level nodes and the links between them.
    Subgraph node ids like "30:10" are not numbers: ComfyUI keeps those nodes in a subgraph."""
    top = {node_id: n for node_id, n in prompt.items() if node_id.isdigit()}
    links = [
        [number, int(value[0]), value[1], int(node_id), 0, "*"]
        for number, (node_id, value) in enumerate(
            (
                (node_id, value)
                for node_id, n in top.items()
                for value in n["inputs"].values()
                if isinstance(value, list) and str(value[0]) in top
            ),
            start=1,
        )
    ]
    nodes = [
        {
            "id": int(node_id),
            "type": n["class_type"],
            "mode": 0,
            "pos": [index * 40, 100],
            "size": [315, 130],
            "inputs": [
                {"name": "in", "link": link[0]} for link in links if link[3] == int(node_id)
            ],
            "outputs": [{"name": "out", "links": [k[0] for k in links if k[1] == int(node_id)]}],
            "widgets_values": [v for v in n["inputs"].values() if not isinstance(v, list)],
        }
        for index, (node_id, n) in enumerate(top.items(), start=1)
    ]
    return {"nodes": nodes, "links": links, "groups": [], "version": 0.4}


def write_batch(args: tuple[int, int, int, str, float]) -> int:
    """Write one generation: 1-4 images sharing an API prompt, stamped seconds apart."""
    seed, index, first_name, out, stamp = args
    rng = random.Random(seed * 1_000_003 + index)
    prompt = api_prompt(rng)
    info = PngInfo()
    info.add_text("prompt", json.dumps(prompt))
    info.add_text("workflow", json.dumps(workflow_for(prompt)))
    folder = Path(out) / time.strftime("%Y-%m-%d", time.localtime(stamp))
    folder.mkdir(parents=True, exist_ok=True)
    count = rng.choice([1, 1, 1, 2, 4])
    for k in range(count):
        path = folder / f"ComfyUI_{first_name + k:07d}_.png"
        color = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), color).save(buf, "PNG", pnginfo=info)
        path.write_bytes(buf.getvalue())
        os.utime(path, (stamp + k * 0.05, stamp + k * 0.05))
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("count", type=int, help="number of images (approximate: batches)")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args()

    out: Path = args.directory
    if out.exists() and any(out.iterdir()):
        parser.error(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    now = time.time()
    batches = []
    name = written = 0
    # Average batch size is 1.8; draw stamps over 90 days, then sort them.
    expected = max(1, round(args.count / 1.8))
    stamps = sorted(now - rng.random() * 90 * DAY for _ in range(expected))
    for index, stamp in enumerate(stamps):
        batches.append((args.seed, index, name, str(out), stamp))
        name += 4

    with ProcessPoolExecutor(args.workers) as pool:
        for count in pool.map(write_batch, batches, chunksize=64):
            written += count

    # About 1% byte-identical copies, for dedupe.
    files = sorted(out.rglob("*.png"))
    for path in rng.sample(files, k=len(files) // 100):
        copy = path.with_name(path.stem + "_copy.png")
        shutil.copy2(path, copy)
        written += 1
    print(f"wrote {written} files to {out}")


if __name__ == "__main__":
    main()
