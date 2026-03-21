import os
import json
import asyncio
import random
import re
import io
import tempfile
import traceback
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import AsyncOpenAI
import httpx
import replicate

# --- 出图模型配置（坚守 PhotoMaker 锁脸 + SDXL 回退）---
IMAGE_MODEL_PRIMARY = os.getenv(
    "IMAGE_MODEL_PRIMARY",
    "stability-ai/sdxl:7762fd07cf82c948538e41f63f77d685e02b063e37e496e96eefd46c929f9bdc",
)

# --- 对话/文本模型（OpenRouter）---
# 按用户要求恢复默认到 GPT-4o；可用 CHAT_MODEL 覆盖。
CHAT_MODEL = os.getenv("CHAT_MODEL", "openai/gpt-4o")

# --- 统一画风配置（彩色柔光电影质感，避免“突然动漫风”与黑白片） ---
STYLE_PRESETS = {
    "mature_romantic": (
        "color image, cinematic romantic photorealistic movie still, warm halo lighting, soft glow bloom, dreamy bokeh, "
        "consistent visual style across a series, realistic lighting, 35mm film look, premium color grading, subtle film grain, "
        "young attractive adults, smooth flawless skin, soft lighting on face, high-end romance film mood, "
        "same character design and consistent appearance, no text, no watermark, not black and white, not monochrome, rich warm colors"
    ),
    "young_cute": (
        "color image, bright romantic photorealistic cinematic still frame, soft glow bloom, dreamy bokeh, "
        "consistent visual style across a series, clean composition, premium movie color grading, subtle film grain, "
        "young attractive adults, soft skin, lighthearted romantic mood, "
        "same character design and consistent appearance, no text, no watermark, not black and white, not monochrome, vivid pastel colors"
    ),
}

# 统一加在每条 Replicate 生图 prompt 最前：压制「黑白画册 / 三拼版 / 伪艺术 B&W」
COLOR_CINEMA_PREFIX = (
    "MANDATORY FULL COLOR RGB photograph — natural skin tones, colored clothing and environment, "
    "warm golden cinematic lighting, rich modern romance-movie color grade, "
    "NOT black and white, NOT monochrome, NOT grayscale, NOT duotone, NOT editorial B&W, "
    "NOT open book layout, NOT two-page spread, NOT triptych catalog, NOT sketchbook panels. "
)

# 美式漫画线稿上色（与「电影剧照」二选一，由 portrait_style 控制）
COMIC_STYLE_PRESETS = {
    "mature_romantic": (
        "color western comic book illustration, bold clean line art, cel shading, vibrant saturated colors, "
        "romantic drama graphic novel panel, NOT live-action photography, NOT photorealistic DSLR still, "
        "consistent character design, young attractive adults, same visual style across series, "
        "no text, no watermark, not black and white, not monochrome, rich comic book colors"
    ),
    "young_cute": (
        "color bright comic illustration, clean lines, soft cel shading, lighthearted romantic graphic novel style, "
        "NOT photorealistic photograph, NOT movie still, vivid pastel comic colors, "
        "no text, no watermark, not black and white, not monochrome"
    ),
}

COLOR_COMIC_PREFIX = (
    "MANDATORY full-color comic BOOK illustration — NOT photograph, NOT movie still, NOT DSLR, NOT 35mm film, "
    "clear line art with cel shading or flat colors, NOT black and white, NOT monochrome grayscale, "
    "NOT triptych catalog, NOT three-panel layout, NOT sketchbook spread. "
)

# 统一追加在每条生图 prompt 末尾（Replicate SDXL / PhotoMaker / 兜底 prompt 均经 _sdxl_generate_image）
# 强调原生 1:1 方图，便于社交分享与前端满幅，避免宽幅黑边
CINEMA_QUALITY_SUFFIX = (
    "square portrait composition, 1:1 aspect ratio native output, centered dramatic scene, "
    "masterpiece, ultra-detailed, 8k resolution, subtle film grain, shallow depth of field, "
    "dramatic chiaroscuro lighting, dramatic shadows, moody atmosphere, rich silk fabric texture, intricate gold embroidery, "
    "subjects centered and perfectly contained within the square frame, full-bleed square image, edge-to-edge, "
    "no letterboxing, no pillarboxing, no split composition, no empty margins."
)

# 强制排除动漫 + 失败兜底（合并进所有生图 negative_prompt）
NO_ANIME_STYLE = (
    "anime, cartoon, comic, drawing, illustration, sketch, 2d, painting, render, vector art, "
    "duplicate characters, unnatural interaction, incomplete frame, whitespace on edges"
)

# 禁止「参考图左右拼接」被模型抄成输出：双联肖像、分屏、黑边留白
NO_SPLIT_COMPOSITION = (
    "diptych, triptych, split screen, split-screen, two panels, side by side portraits, "
    "two photos side by side, collage layout, collage of two images, before and after, "
    "twin panel layout, duplicate panel, letterboxing, pillarboxing, black bars, "
    "empty black area, large black void, negative space on the side, unused canvas area"
)

# 与 frontend/public/split_faces 文件名一致（cinematic / comic）
_SPLIT_FACE_MALE_CINEMATIC: dict[str, str] = {
    "Adrien": "cinematic_male_adrien_top.png",
    "Richard": "cinematic_male_richard_top.png",
    "Damon": "cinematic_male_damon_bottom.png",
    "Lucas": "cinematic_male_lucas_bottom.png",
}
_SPLIT_FACE_MALE_COMIC: dict[str, str] = {
    "Adrien": "comic_male_adrien_top.png",
    "Richard": "comic_male_richard_top.png",
    "Damon": "comic_male_damon_bottom.png",
    "Lucas": "comic_male_lucas_bottom.png",
}
_SPLIT_FACE_FEMALE_CINEMATIC: dict[str, str] = {
    "Fresh Chic": "cinematic_female_fresh_chic.png",
    "Night Elegance": "cinematic_female_night_elegance.png",
    "Executive Aura": "cinematic_female_executive_aura.png",
    "Grace Classic": "cinematic_female_grace_classic.png",
}
_SPLIT_FACE_FEMALE_COMIC: dict[str, str] = {
    "Fresh Chic": "comic_female_fresh_chic.png",
    "Night Elegance": "comic_female_night_elegance.png",
    "Executive Aura": "comic_female_executive_aura.png",
    "Grace Classic": "comic_female_grace_classic.png",
}


def _split_face_filenames(character: str, female_name: str, portrait_style: str) -> tuple[str, str]:
    ps = (portrait_style or "cinematic").strip().lower()
    if ps == "comic":
        m = _SPLIT_FACE_MALE_COMIC.get(character, _SPLIT_FACE_MALE_COMIC["Adrien"])
        f = _SPLIT_FACE_FEMALE_COMIC.get(female_name, _SPLIT_FACE_FEMALE_COMIC["Night Elegance"])
    else:
        m = _SPLIT_FACE_MALE_CINEMATIC.get(character, _SPLIT_FACE_MALE_CINEMATIC["Adrien"])
        f = _SPLIT_FACE_FEMALE_CINEMATIC.get(female_name, _SPLIT_FACE_FEMALE_CINEMATIC["Night Elegance"])
    return m, f


def _split_faces_dir() -> str:
    """
    优先使用与 main.py 同目录下的 split_faces/（Docker / Fly 镜像内会打包，避免依赖 ../frontend）。
    本地开发仍可用仓库里的 frontend/public/split_faces。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(here, "split_faces")
    if os.path.isdir(bundled):
        return bundled
    return os.path.abspath(os.path.join(here, "..", "frontend", "public", "split_faces"))


def _split_face_local_paths(character: str, female_name: str, portrait_style: str) -> tuple[str, str]:
    mf, ff = _split_face_filenames(character, female_name, portrait_style)
    base = _split_faces_dir()
    return os.path.join(base, mf), os.path.join(base, ff)


def _concat_two_face_refs_horizontal(left_path: str, right_path: str) -> str | None:
    """左右拼接男女参考脸，供 PhotoMaker 单 input_image；失败返回 None。"""
    try:
        from PIL import Image

        if not (os.path.isfile(left_path) and os.path.isfile(right_path)):
            return None
        im1 = Image.open(left_path).convert("RGB")
        im2 = Image.open(right_path).convert("RGB")
        h = max(im1.height, im2.height)
        w1 = int(im1.width * h / im1.height)
        w2 = int(im2.width * h / im2.height)
        im1 = im1.resize((w1, h), Image.Resampling.LANCZOS)
        im2 = im2.resize((w2, h), Image.Resampling.LANCZOS)
        total = Image.new("RGB", (w1 + w2, h))
        total.paste(im1, (0, 0))
        total.paste(im2, (w1, 0))
        fd, out = tempfile.mkstemp(suffix=".png", prefix="ww_dual_ref_")
        os.close(fd)
        total.save(out, format="PNG")
        return out
    except Exception as e:
        print(f"⚠️ _concat_two_face_refs_horizontal: {e}")
        return None


def _is_photomaker_disposable_temp(path: str) -> bool:
    """仅删除临时拼接的参考 PNG（ww_dual_ref_*），绝不删除 split_faces 仓库内资源。"""
    if not path or not isinstance(path, str):
        return False
    if not path.endswith(".png"):
        return False
    return os.path.basename(path).startswith("ww_dual_ref_")


def _build_ref_image_line_prompt(male_name: str, female_name: str, scene_hint: str) -> str:
    """1:1 方图开场句 + ref image 对应选中角色（双人或单人）。"""
    mn = (male_name or "").strip() or "male lead"
    fn = (female_name or "").strip()
    sh = (scene_hint or "").strip() or "a dimly lit, sophisticated ballroom"
    if fn:
        return (
            f"A square portrait composition, 1:1 aspect ratio, centered dramatic scene capturing {mn} "
            f"(male, facial identity from reference image) and {fn} "
            f"(female, matching the selected protagonist look described in this prompt) "
            f"interacting in {sh}. Both characters centered and contained within the square frame. "
        )
    return (
        f"A square portrait composition, 1:1 aspect ratio, centered dramatic scene capturing {mn} "
        f"(male, facial identity from reference image) in {sh}. "
    )

# 禁止“两个男的同框”：所有双人图都必须是 1 男 1 女
NO_TWO_MALES = (
    "two men, 2 men, two males, 2 males, 2boys, two boys, second man, another man, "
    "two male characters, double male, male duo, two guys, pair of men, two men in frame, "
    "only men, both men, two male faces, no woman in frame, all male, male only scene"
)

# 禁止畸形/假手、奇怪手势、短粗手指等
BAD_HANDS = (
    "deformed hands, bad hands, missing fingers, fused fingers, extra fingers, "
    "claw hand, prosthetic arm, cast arm, bandaged arm, mannequin hand, mannequin arm, "
    "smooth hand, no fingers, mutated hand, ugly hand, disfigured hand, "
    "amputee, stump arm, blob hand, malformed hand, wrong number of fingers, "
    "smooth limb, featureless arm, mannequin limb, "
    "stubby fingers, short fingers, lumpy knuckles, lumpy hands, blocky hand, stiff hand, "
    "clenched fist in foreground, raised fist, weird hand gesture, unnatural hand pose, "
    "bent fingers, compressed fingers, hand gesture focus, hands up center frame"
)
# 禁止奇怪胳膊：过粗、比例失调、肌肉感错位等
BAD_ARMS = (
    "thick arm, muscular arm on woman, disproportionate arm, distorted arm, bulky arm, "
    "oversized bicep, swollen arm, unnatural arm proportion, thick bicep, bodybuilder arm, "
    "weird arm angle, contorted arm, elongated arm, arm anatomy wrong"
)

# 防变异驱魔咒：针对人体结构（尤其手）的死刑词汇，避免怪物手/变性
ANTI_MUTATION_CURSE = (
    "3 people, worst quality, deformed, monochrome, text, watermark, "
    "bad anatomy, mutated hands, fused fingers, extra limbs, missing arms, "
    "disfigured, bad proportions, poorly drawn hands, twisted arms, "
    "two men, yaoi, cloned face"
)

# 双人构图机位铁律：防止男主被挤出画框，镜头必须同时框住两人
TWO_SHOT_CAMERA_DIRECTIVE = (
    "Two-shot composition, both characters clearly visible in the frame, medium shot from the waist up, "
    "no single-person close-up, no cropping out the other character. "
)
# 负面：禁止单人特写裁掉另一人
NO_SOLO_CROP = "single person close-up, cropped to one face, other character out of frame, only one person visible, half face cut off"

# 多余面孔 / 多余人 —— 终极黑名单（PhotoMaker + SDXL 均会合并进去）
REPLICATE_NEGATIVE_EXTRA_FACES = (
    "mutated faces, fused faces, fused face, extra faces, duplicate face, two faces one head, "
    "extra people, extra person, crowd, crowds, groups, group shot, group photo, gathering, "
    "disfigured, deformed face, many people, huge crowd, 3 people, three people, third person, "
    "fourth person, background crowd in focus, audience faces, stranger beside subject, "
    "two men, yaoi, cloned face, identical duplicate faces, split face, "
    "text, watermark, subtitle, logo, caption, letters, typography"
)

# Replicate API 专用：防变异+防双胞胎+防文字+怪手怪臂 + 多余面孔黑名单
REPLICATE_NEGATIVE_ULTIMATE = (
    f"{REPLICATE_NEGATIVE_EXTRA_FACES}, "
    "worst quality, deformed, monochrome, "
    "bad anatomy, mutated hands, fused fingers, extra limbs, missing arms, "
    "bad proportions, poorly drawn hands, twisted arms, "
    "two women, 2 girls, two females, both women, female duo, no man in frame, only women, "
    "stubby fingers, lumpy hands, blocky hand, weird hand gesture, clenched fist, hands up center, "
    "thick arm, disproportionate arm, bulky arm, oversized bicep, distorted arm, "
    f"{NO_SOLO_CROP}, "
    f"{NO_ANIME_STYLE}, {NO_SPLIT_COMPOSITION}"
)

# 单人构图专用：在 ULTIMATE 之上再压「第二人入画」
REPLICATE_NEGATIVE_SOLO_SUBJECT = (
    "two people, 2 people, second person, couple, duo, 1girl, woman in frame, female in frame, "
    "girl beside man, two subjects, multiple subjects, reflection second face, mirror duplicate person"
)

# 基础负面词（始终启用，包含 NSFW 屏蔽和黑白屏蔽 + 多余面孔黑名单）
NEGATIVE_PROMPT_BASE = (
    f"{REPLICATE_NEGATIVE_EXTRA_FACES}, "
    "anime, manga, cartoon, illustration, painting, oil painting, digital art, concept art, sketch, "
    "chibi, 3d render, cgi, plastic skin, "
    "lowres, blurry, bad anatomy, extra fingers, deformed, "
    "black and white, monochrome, grayscale, desaturated, low-saturation, "
    "nudity, explicit, fetish, "
    f"{NO_TWO_MALES}, {BAD_HANDS}, {BAD_ARMS}, {ANTI_MUTATION_CURSE}, "
    f"{NO_ANIME_STYLE}, {NO_SPLIT_COMPOSITION}"
)

# 漫画模式：允许「插画」，禁止「照片写实」与多余面孔
NEGATIVE_PROMPT_COMIC = (
    f"{REPLICATE_NEGATIVE_EXTRA_FACES}, "
    "photorealistic, photorealism, hyperrealistic, DSLR photograph, movie still, 35mm film, cinematic photograph, "
    "chibi, 3d render, cgi, plastic skin, "
    "lowres, blurry, bad anatomy, extra fingers, deformed, "
    "black and white, monochrome, grayscale, desaturated, low-saturation, "
    "nudity, explicit, fetish, "
    f"{NO_TWO_MALES}, {BAD_HANDS}, {BAD_ARMS}, {ANTI_MUTATION_CURSE}, "
    f"{NO_ANIME_STYLE}, {NO_SPLIT_COMPOSITION}"
)

# 未成年人额外负面词（在 BASE 之上再加一层，收紧姿态与氛围）
NEGATIVE_PROMPT_TEEN_EXTRA = (
    "deep kiss, making out, lingerie, cleavage, seductive pose, "
    "bedroom scene, lying on bed together, suggestive touching, "
    "overly revealing clothing, erotic, sexualized pose"
)

CHARACTER_PROFILES = {
    "Adrien": (
        "young handsome man in his 20s, stylish golden-blonde hair, bright warm smile, clean-shaven face (no beard), "
        "light tailored beige suit with elegant styling"
    ),
    "Richard": (
        "young handsome man in his late 20s, short dark hair, deep intense eyes, "
        "sharp navy blue three-piece suit, refined timeless styling"
    ),
    "Damon": (
        "young handsome man in his 20s, slightly messy brown hair, relaxed sweet smile, "
        "light casual jacket, sunny carefree styling"
    ),
    "Lucas": (
        "young handsome man in his 20s, wavy dark hair slightly covering eyes, cool expression, "
        "stylish black leather jacket, cinematic neon mood"
    ),
}

# 角色反向约束：用于 negative prompt，减少“串脸串发色”
CHARACTER_NEGATIVE = {
    "Adrien": "silver hair, black hair, dark brown hair, red hair, buzz cut, beard, mustache, stubble, mysterious gloomy expression, older than 40",
    "Richard": "silver hair, bright dyed hair, youthful teen look, streetwear hoodie",
    "Damon": "silver hair, strict formal suit, gloomy mysterious expression, old-fashioned styling, teen look, black slicked hair",
    "Lucas": "blonde hair, clean corporate suit, cheerful broad smile, bright sunny daylight mood, teen look",
}

CHARACTER_IDENTITY_LOCK = {
    "Adrien": "golden-blonde hair is mandatory, clean-shaven face is mandatory (no beard/mustache), warm light eyes, elegant beige suit, late-20s mature look",
    "Richard": "short dark hair is mandatory, deep intense eyes, refined navy three-piece suit, late-20s mature gentleman look",
    "Damon": "slightly messy brown hair is mandatory, relaxed sweet smile, light casual jacket, youthful sunny vibe",
    "Lucas": "wavy dark hair partly covering eyes is mandatory, stylish black leather jacket, cool expression, neon-night cinematic vibe",
}

# --- 配置加载（先加载 .env，代理等由环境变量可选配置）---
_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=True)

# 若只配置了 OPENROUTER_PROXY，同步给 HTTP_PROXY/HTTPS_PROXY，让 Replicate 等库也走代理
_proxy = os.getenv("OPENROUTER_PROXY", "").strip().strip('"').strip("'")
if _proxy and not os.getenv("HTTP_PROXY"):
    os.environ["HTTP_PROXY"] = _proxy
if _proxy and not os.getenv("HTTPS_PROXY"):
    os.environ["HTTPS_PROXY"] = _proxy

def _clean_env_value(v: str | None) -> str | None:
    if v is None:
        return None
    out = v.strip().strip('"').strip("'")
    return out or None

OPENROUTER_API_KEY = _clean_env_value(os.getenv("OPENROUTER_API_KEY"))
OPENAI_API_KEY = _clean_env_value(os.getenv("OPENAI_API_KEY")) or OPENROUTER_API_KEY
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

app = FastAPI()

# CORS: 明确允许本地开发前端访问（浏览器会严格校验 Origin）
origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "https://word-wizard-backend.fly.dev",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 启动时提醒：浏览器开代理 ≠ 后端走代理；未配置则 OpenRouter 仍直连，易 403 region
_or_proxy = _clean_env_value(os.getenv("OPENROUTER_PROXY")) or _clean_env_value(os.getenv("HTTP_PROXY")) or _clean_env_value(os.getenv("HTTPS_PROXY"))
if _or_proxy:
    try:
        from urllib.parse import urlparse

        u = urlparse(_or_proxy)
        host = u.hostname or "?"
        port = u.port or ("1080" if "socks" in (u.scheme or "").lower() else "?")
        print(f"👉 OpenRouter/Replicate: 已配置代理 ({u.scheme}://{host}:{port})")
    except Exception:
        print("👉 OpenRouter/Replicate: 已配置代理（OPENROUTER_PROXY / HTTP_PROXY）")
else:
    print(
        "👉 OpenRouter/Replicate: 未配置代理（直连）。若报 region 403，请在 backend/.env 写 "
        "OPENROUTER_PROXY=http://127.0.0.1:8001（端口改成 Clash/V2Ray 的「HTTP 代理」端口），然后重启后端。"
    )

# Serve repo-root `asset/` folder (e.g., bgm files) at `/asset/*`
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ASSET_DIR = os.path.join(_REPO_ROOT, "asset")
if os.path.isdir(_ASSET_DIR):
    app.mount("/asset", StaticFiles(directory=_ASSET_DIR), name="asset")

# 与 _split_faces_dir() 一致，便于 Fly 上 /split_faces/*.png 可被 Replicate 拉取（替代 localhost 参考图）
_SPLIT_FACES_MOUNT_DIR = _split_faces_dir()
if os.path.isdir(_SPLIT_FACES_MOUNT_DIR):
    app.mount("/split_faces", StaticFiles(directory=_SPLIT_FACES_MOUNT_DIR), name="split_faces")
    print(f"👉 split_faces 静态资源: /split_faces → {_SPLIT_FACES_MOUNT_DIR}")

# --- 请求模型 ---
class GetWordsRequest(BaseModel):
    scene: str
    character: str
    word_count: int = 3  # 前端传来的词数，默认是3
    story_style: str = Field(default="mature_romantic", description="mature_romantic | young_cute")
    recent_words: list[str] = Field(default_factory=list, description="Words shown recently; avoid repeating")
    story_mode: str = Field(default="romance", description="romance | adventure")
    protagonist_profile: str = Field(
        default="young woman, shoulder-length dark hair, smart casual outfit",
        description="User protagonist appearance profile for image consistency",
    )
    is_adult: bool = Field(default=False, description="True if user confirmed 18+ at entry")

class ProcessTurnRequest(BaseModel):
    sentence: str
    required_words: list[str]
    scene: str
    character: str
    story_style: str = Field(default="mature_romantic", description="mature_romantic | young_cute")
    story_mode: str = Field(default="romance", description="romance | adventure")
    protagonist_profile: str = Field(
        default="young woman, shoulder-length dark hair, smart casual outfit",
        description="User protagonist appearance profile for image consistency",
    )
    protagonist_name: str = Field(
        default="",
        description="女主人设名（如 Night Elegance），用于生图 prompt 双人同框点名",
    )
    portrait_style: str = Field(default="cinematic", description="cinematic | comic")
    character_reference_url: str | None = None
    protagonist_reference_url: str | None = None
    male_avatar_url: str = ""
    female_avatar_url: str = ""
    is_adult: bool = Field(default=False, description="True if user confirmed 18+ at entry")

class FinalStoryRequest(BaseModel):
    sentences: list[str]
    scene: str
    character: str
    story_style: str = Field(default="mature_romantic", description="mature_romantic | young_cute")
    story_mode: str = Field(default="romance", description="romance | adventure")
    protagonist_profile: str = Field(
        default="young woman, shoulder-length dark hair, smart casual outfit",
        description="User protagonist appearance profile for image consistency",
    )
    protagonist_name: str = Field(
        default="",
        description="女主人设名，与 process_turn 一致",
    )
    is_adult: bool = Field(default=False, description="True if user confirmed 18+ at entry")
    character_reference_url: str | None = None
    protagonist_reference_url: str | None = None
    portrait_style: str = Field(default="cinematic", description="cinematic | comic — 终章配图与回合一致")

# --- 配置 OpenRouter 客户端 ---
# 代理可选：仅在 .env 中设置 OPENROUTER_PROXY 或 HTTP_PROXY 时使用（如国内需走代理）；不设置则直连。
def get_async_openai_client():
    proxy_url = (
        _clean_env_value(os.getenv("OPENROUTER_PROXY"))
        or _clean_env_value(os.getenv("HTTPS_PROXY"))
        or _clean_env_value(os.getenv("HTTP_PROXY"))
    )
    http_client = httpx.AsyncClient(proxy=proxy_url, timeout=60.0) if proxy_url else httpx.AsyncClient(timeout=60.0)
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OpenRouter API key missing. Please set OPENAI_API_KEY or OPENROUTER_API_KEY in backend/.env."
        )
    return AsyncOpenAI(api_key=OPENAI_API_KEY, base_url="https://openrouter.ai/api/v1", http_client=http_client)


def _openrouter_model_chain(primary: str) -> list[str]:
    """主模型 + CHAT_MODEL_FALLBACK（逗号分隔）+ OpenAI / Google 备用。"""
    chain: list[str] = [primary]
    fb = os.getenv("CHAT_MODEL_FALLBACK", "") or ""
    for part in fb.split(","):
        p = _clean_env_value(part.strip())
        if p and p not in chain:
            chain.append(p)
    # 默认优先 OpenAI 族，最后再回退 Gemini
    for m in (
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "openai/gpt-5.2",
        "openai/gpt-5",
        "google/gemini-2.0-flash-001",
    ):
        if m not in chain:
            chain.append(m)
    return chain


def _is_openrouter_region_403(e: BaseException) -> bool:
    raw = str(e)
    low = raw.lower()
    return ("403" in raw or "error code: 403" in low) and (
        "region" in low or "not available" in low or "in your region" in low
    )


async def _openrouter_chat(client: AsyncOpenAI, **kwargs):
    """遇 403（地区不可用）时按链依次换模型，直到成功。"""
    kw = dict(kwargs)
    trace: list[str] | None = kw.pop("_model_trace", None)
    primary = kw.get("model") or CHAT_MODEL
    chain = _openrouter_model_chain(primary)
    last_err: BaseException | None = None
    for i, model in enumerate(chain):
        kw["model"] = model
        try:
            resp = await client.chat.completions.create(**kw)
            if trace is not None:
                trace.append(model)
            if i > 0:
                print(f"✅ OpenRouter: 本请求实际使用模型 → {model}")
            return resp
        except Exception as e:
            last_err = e
            if _is_openrouter_region_403(e) and i + 1 < len(chain):
                nxt = chain[i + 1]
                print(f"⚠️ OpenRouter: {model} region 403 → try {nxt}")
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("OpenRouter: no model in chain")


# PhotoMaker 模型：更稳的“锁脸/换脸”路线（单参考图）
# 注意：prompt 需要包含 "img" 这个 token（模型要求）
IMAGE_MODEL_PHOTOMAKER = "tencentarc/photomaker:ddfc2b08d209f9fa8c1eca692712918bd449f695dabb4a958da31802a9570fe4"


def _replicate_safe_avatar_url(url: str) -> str:
    """Replicate 无法拉取 http://localhost/… 参考图；改为 PUBLIC_BASE_URL 下同路径（须已挂载 /split_faces）。"""
    u = (url or "").strip()
    if not u.startswith("http"):
        return u
    try:
        from urllib.parse import urlparse

        p = urlparse(u)
        if p.hostname not in ("localhost", "127.0.0.1"):
            return u
        base = (os.getenv("PUBLIC_BASE_URL") or "https://backend-black-snow-4374.fly.dev").rstrip("/")
        return f"{base}{p.path}" + (f"?{p.query}" if p.query else "")
    except Exception:
        return u


async def _sdxl_generate_image(
    prompt: str,
    seed: int | None = None,
    extra_negative: str | None = None,
    male_img: str = "",
    female_img: str = "",
    is_adult: bool = False,
    composition: str = "duo",
    dinner_scene: bool = False,
    portrait_style: str = "cinematic",
    ref_image_line: str = "",
    ref_male_character: str = "",
    ref_female_name: str = "",
):
    """
    返回 (image_url, nsfw_blocked: bool)
    出图仅使用 Replicate：PhotoMaker（单人锁脸）与 SDXL 文生图；本项目未使用 DALL·E 3。
    SDXL 输出强制 width=height=1024（原生 1:1 方图）。
    ref_image_line：方图开场句 + ref image（含男女名）。
    ref_male_character / ref_female_name：用于定位 split_faces 下男主 PNG；双人电影场景跳过 PhotoMaker，走 SDXL。
    """
    _ps = (portrait_style or "cinematic").strip().lower()
    is_comic = _ps == "comic"
    solo = composition.strip().lower() == "solo"
    color_pre = COLOR_COMIC_PREFIX if is_comic else COLOR_CINEMA_PREFIX
    core = (prompt or "").strip()
    core = core.rstrip().rstrip(".").strip()
    suffix = CINEMA_QUALITY_SUFFIX
    ref_line = (ref_image_line or "").strip()

    # 双人 + 电影质感：仅从入参解析【男主 + 女主】两名（禁止额外角色）；core = 上游剧情/场景正文
    negative_prompt = ""
    if not is_comic and not solo:
        # 入参即「payload」语义：仅信任 ref_male_character / ref_female_name + 内置外貌库（与前端选人一致）
        male_key = (ref_male_character or "").strip() or "Adrien"
        female_key = (ref_female_name or "").strip() or "Night Elegance"
        male_feat = CHARACTER_PROFILES.get(male_key, CHARACTER_PROFILES["Adrien"])
        _female_looks = {
            "Fresh Chic": "young woman, cute short bob hair, cozy oversized sweater, soft smooth skin, warm approachable look",
            "Night Elegance": "young woman, long straight black hair, elegant silk evening gown, refined sharp features, almond eyes",
            "Executive Aura": "woman, sharp confident eyes, tailored black blazer, confident office elegance",
            "Grace Classic": "woman, auburn hair in elegant updo, classic chic vintage dress, timeless grace",
        }
        female_feat = _female_looks.get(female_key, _female_looks["Night Elegance"])
        translated_text = core
        image_prompt = (
            f"A masterpiece square portrait composition, 1:1 aspect ratio, centered dramatic scene. "
            f"STRICTLY TWO PEOPLE ONLY — one adult man and one adult woman in the SAME square frame, both centered and perfectly contained: "
            f"1. [{male_key}, male — {male_feat}] "
            f"2. [{female_key}, female — {female_feat}]. "
            f"MANDATORY FRAMING: medium-wide establishing view within the square (NOT extreme face close-up), BOTH man and woman clearly visible with environment matching the story; "
            f"if outdoor/park is implied, show trees, path, sky — NOT a studio headshot crop. "
            f"Action: {translated_text}. "
            f"Style: photorealistic, 8k, dramatic chiaroscuro lighting; natively fill the entire square canvas edge-to-edge, not a cropped landscape."
        )
        negative_prompt = (
            "3 people, three faces, extra characters, crowd, background characters, anime, cartoon, duplicate characters, two males, deformed, "
            "solo portrait, watermark, text, white borders, vertical diptych, stacked portraits, split layout, "
            "only one woman, solo female, single person, only one face, missing man, no man, male cropped out, "
            "extreme close-up eyes only, beauty macro crop, empty black area, letterboxing, unused canvas"
        )
        prompt = image_prompt
        merged_negative_parts = [negative_prompt]
        if not is_adult:
            merged_negative_parts.append(NEGATIVE_PROMPT_TEEN_EXTRA)
        if extra_negative:
            merged_negative_parts.append(extra_negative)
        merged_negative = ", ".join(merged_negative_parts)
    else:
        if ref_line:
            assembled = f"{ref_line} {color_pre} {core}. {suffix}".strip()
        else:
            assembled = f"{color_pre} {core}. {suffix}".strip() if core else f"{color_pre} {suffix}".strip()
        prompt = assembled

        merged_negative_parts = [NEGATIVE_PROMPT_COMIC if is_comic else NEGATIVE_PROMPT_BASE]
        if not is_adult:
            merged_negative_parts.append(NEGATIVE_PROMPT_TEEN_EXTRA)
        if extra_negative:
            merged_negative_parts.append(extra_negative)
        merged_negative = ", ".join(merged_negative_parts)

    def _is_nsfw(msg: str) -> bool:
        return ("NSFW" in msg) or ("nsfw" in msg)

    def _is_rate_limited(msg: str) -> bool:
        m = msg.lower()
        return ("429" in m) or ("throttled" in m) or ("rate limit" in m)

    def _photomaker_negative() -> str:
        if negative_prompt:
            parts = [negative_prompt]
            if not is_adult:
                parts.append(NEGATIVE_PROMPT_TEEN_EXTRA)
            if extra_negative:
                parts.append(extra_negative)
            return ", ".join(parts)
        parts = [REPLICATE_NEGATIVE_ULTIMATE]
        if solo:
            parts.append(REPLICATE_NEGATIVE_SOLO_SUBJECT)
        if extra_negative:
            parts.append(extra_negative)
        return ", ".join(parts)

    _pm_style = "Digital Art" if is_comic else "Cinematic"

    # --- 参考图：split_faces 本地 PNG → 拼接或单张 → PhotoMaker ---
    photomaker_input: Any = None
    photomaker_input_desc = ""
    male_name = (ref_male_character or "").strip()
    female_name = (ref_female_name or "").strip() or "Night Elegance"
    if male_name:
        mp, _fp = _split_face_local_paths(male_name, female_name, portrait_style)
        # 禁止左右拼接双脸：PhotoMaker 会照抄成「左右两张脸 + 右侧黑边」，与「单场景电影画面」冲突。
        if os.path.isfile(mp):
            photomaker_input = mp
            photomaker_input_desc = f"{'solo' if solo else 'duo'}_male_local:{mp}"
    if photomaker_input is None and (male_img or "").strip().startswith("http"):
        photomaker_input = _replicate_safe_avatar_url(male_img.strip())
        photomaker_input_desc = f"url:{str(photomaker_input)[:80]}..."

    # PhotoMaker 为单人脸身份模型，双人场景极易变成「单人脸特写 / 性别错乱」；双人电影质感一律走 SDXL 文生图保构图。
    if (not solo) and (not is_comic):
        if photomaker_input is not None:
            print("👉 duo cinematic: skip PhotoMaker, use SDXL two-shot (avoid single-face collapse)")
        photomaker_input = None

    if photomaker_input is not None:
        print(f"PhotoMaker input ({photomaker_input_desc}) composition={composition} style={_pm_style}")
        base_prompt = prompt if ("img" in prompt.lower()) else f"{prompt} img"
        if solo:
            pm_prompt = (
                "Strictly only one person, single-subject composition, exactly one human in frame, one face only, "
                "one man only, no other people visible anywhere. "
                f"{base_prompt}"
            )
        else:
            dual_hint = (
                "The input_image is ONLY a facial-identity reference for the MALE lead — embed him naturally in the scene. "
                "You MUST also render exactly ONE woman (female) in the same frame — one man + one woman, never two women. "
                "The woman must match the female protagonist described in the prompt text. "
                "Generate ONE single continuous photorealistic wide frame — NOT vertical stack, NOT two stacked headshots, NOT a diptych, NOT split-screen. "
                "Full-bleed, edge-to-edge, no black bars. "
            )
            if dinner_scene:
                pm_prompt = (
                    dual_hint
                    + TWO_SHOT_CAMERA_DIRECTIVE
                    + "RESTAURANT DINNER SCENE — medium-wide or wide shot: upscale restaurant interior, warm candlelight. "
                    "A dining table with VISIBLE plates, food, wine or water glasses and cutlery occupies the lower/center frame (mandatory). "
                    "One man and one woman seated at this SAME table, engaged in conversation during dinner. "
                    "FORBIDDEN: extreme close-up on eyes only, forehead-only crop, face-only crop with no table, empty background with no meal props. "
                    "No third person. "
                    + base_prompt
                )
            else:
                pm_prompt = (
                    dual_hint
                    + TWO_SHOT_CAMERA_DIRECTIVE
                    + "Strictly only two people: exactly 1boy and exactly 1girl. One man (male lead) and one woman (protagonist). "
                    "Not two women, not two men. Not three people. Environmental two-shot: show setting and spatial context, not twin headshot panels. "
                    "Hands natural; avoid giant face crops that erase the background. "
                    + base_prompt
                )

        def _input_image_for_replicate() -> Any:
            if isinstance(photomaker_input, str) and photomaker_input.startswith("http"):
                return photomaker_input
            if isinstance(photomaker_input, str) and os.path.isfile(photomaker_input):
                with open(photomaker_input, "rb") as f:
                    return io.BytesIO(f.read())
            return photomaker_input

        backoffs = [0, 3, 6, 12, 20]
        last_err = None
        for wait_s in backoffs:
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            try:
                img_payload = _input_image_for_replicate()
                input_data = {
                    "prompt": pm_prompt,
                    "negative_prompt": _photomaker_negative(),
                    "input_image": img_payload,
                    "num_steps": 30,
                    "style_name": _pm_style,
                }
                output = await asyncio.wait_for(
                    replicate.async_run(IMAGE_MODEL_PHOTOMAKER, input=input_data),
                    timeout=60.0,
                )
                if isinstance(output, (list, tuple)) and output:
                    out_url = str(output[0])
                else:
                    out_url = str(output)
                if _is_photomaker_disposable_temp(photomaker_input):
                    try:
                        os.remove(photomaker_input)
                    except OSError:
                        pass
                return out_url, False
            except asyncio.TimeoutError:
                last_err = RuntimeError("Replicate PhotoMaker generation timed out after 60 seconds")
                print("REPLICATE ERROR (PhotoMaker): Timeout - no response after 60 seconds")
                break
            except Exception as e:
                msg = str(e)
                last_err = e
                print(f"REPLICATE ERROR (PhotoMaker): {msg}")
                print(f"   model={IMAGE_MODEL_PHOTOMAKER}")
                print(f"   traceback:\n{traceback.format_exc()}")
                if _is_nsfw(msg):
                    if _is_photomaker_disposable_temp(photomaker_input):
                        try:
                            os.remove(photomaker_input)
                        except OSError:
                            pass
                    return None, True
                if _is_rate_limited(msg):
                    continue
                break
        if last_err:
            print(f"Falling back to primary SDXL (PhotoMaker failed): {last_err}")
        if _is_photomaker_disposable_temp(photomaker_input):
            try:
                os.remove(photomaker_input)
            except OSError:
                pass

    # SDXL（Replicate stability-ai/sdxl）：强制 1024×1024 原生方图，与 prompt 中 1:1 描述一致（无 DALL·E 分支）
    _w, _h = 1024, 1024
    primary_input = {
        "prompt": prompt,
        "negative_prompt": merged_negative,
        "width": _w,
        "height": _h,
    }
    backoffs = [0, 2, 4, 8, 15]
    last_err = None
    for wait_s in backoffs:
        if wait_s > 0:
            await asyncio.sleep(wait_s)
        try:
            input_payload = dict(primary_input)
            if seed is not None:
                input_payload["seed"] = seed
            output = await asyncio.wait_for(
                replicate.async_run(IMAGE_MODEL_PRIMARY, input=input_payload),
                timeout=45.0,
            )
            image_url = list(output)[0].url
            return image_url, False
        except asyncio.TimeoutError:
            last_err = RuntimeError("Replicate image generation timed out after 45 seconds")
            print("REPLICATE ERROR: Timeout - no response after 45 seconds")
            break
        except Exception as e:
            msg = str(e)
            last_err = e
            print(f"REPLICATE ERROR (primary SDXL): {msg}")
            print(f"   traceback:\n{traceback.format_exc()}")
            if _is_nsfw(msg):
                return None, True
            if _is_rate_limited(msg):
                continue
            break

    raise last_err if last_err else RuntimeError("Image generation failed without details")


def _build_storyline(scene: str, character: str, story_mode: str):
    if story_mode == "adventure":
        return {
            "title": "Adventure Route",
            "intro": (
                f"In this adventure route, you and {character} step into {scene} and stumble upon a hidden clue. "
                "What begins as curiosity quickly becomes a shared journey of small trials, risky choices, and growing trust. "
                "As you move forward together, each scene reveals a little more danger and a little more connection."
            ),
        }
    return {
        "title": "Romance Route",
        "intro": (
            f"In this romance route, you and {character} meet in {scene} and ease into a gentle, cinematic date. "
            "Through small conversations, shared moments, and subtle emotional shifts, the atmosphere gradually warms up. "
            "This story focuses on chemistry, mutual understanding, and the feeling of getting closer scene by scene."
        ),
    }


def _character_appearance(name: str) -> str:
    return CHARACTER_PROFILES.get(name, CHARACTER_PROFILES["Adrien"])


def _character_negative(name: str) -> str:
    return CHARACTER_NEGATIVE.get(name, "")


def _character_identity_lock(name: str) -> str:
    return CHARACTER_IDENTITY_LOCK.get(name, CHARACTER_IDENTITY_LOCK["Adrien"])


def _is_openrouter_credit_issue(msg: str) -> bool:
    m = (msg or "").lower()
    return (
        "error code: 402" in m
        or "requires more credits" in m
        or "can only afford" in m
        or "insufficient credits" in m
    )

def _is_openrouter_auth_issue(msg: str) -> bool:
    m = (msg or "").lower()
    return (
        "error code: 401" in m
        or "missing authentication header" in m
        or "unauthorized" in m
        or "invalid api key" in m
    )

def _is_region_blocked(msg: str) -> bool:
    m = (msg or "").lower()
    return ("not available in your region" in m) or ("error code: 403" in m and "region" in m)


def _is_llm_connection_error(msg: str) -> bool:
    m = (msg or "").lower()
    return (
        "connection error" in m
        or "connection refused" in m
        or "connecterror" in m
        or "failed to establish" in m
        or "name or service not known" in m
        or "getaddrinfo failed" in m
        or "network is unreachable" in m
        or "proxy error" in m
        or "407" in m
    )


def _contains_word_family(text: str, base_word: str) -> bool:
    """检查句子中是否出现 base_word 或其常见变体（如 invited=invite+d, dinner=dinner）。"""
    t = text.lower()
    w = base_word.lower().strip()
    if not w:
        return True
    # 常见屈折：s, ed, ing, 以及 base 以 e 结尾时的 d（如 invite+d=invited）
    pattern = rf"\b{re.escape(w)}(s|ed|ing|d|er|est)?\b"
    if re.search(pattern, t):
        return True
    # 兼容：base 以 e 结尾时，过去式常为 +d 而非 +ed（invited, liked）
    if w.endswith("e"):
        pattern_d = rf"\b{re.escape(w)}d\b"
        if re.search(pattern_d, t):
            return True
    return False


def _extract_scene_anchors(sentence: str) -> list[str]:
    s = sentence.lower()
    anchors: list[str] = []
    mapping = {
        "supermarket": "inside a Chinese supermarket aisle with visible shelves and grocery baskets",
        "grocery": "groceries and shopping baskets visible",
        "bus": "bus stop or roadside transit context with visible bus/stop sign",
        "got off the bus": "both characters just got off a bus and start walking together",
        "get off the bus": "both characters stepping away from a bus and moving forward together",
        "walked": "both characters walking side by side in the same direction",
        "walk": "clear walking motion from both characters, not static posing",
        "warm": "warm outdoor weather vibe (golden sunlight, light clothing movement)",
        "coffee": "coffee shop or cafe setting with visible coffee cups on table",
        "cafe": "cafe interior or outdoor cafe seating with coffee context",
        "date": "romantic date context with two-character interaction",
        "chatted": "both characters chatting face-to-face with active expressions",
        "happily": "happy expressions and relaxed positive body language",
        "cook": "home kitchen setting with ingredients on the counter",
        "home": "cozy home interior context",
        "dinner": "dinner table with visible cooked dishes/plates/cutlery and food-focused composition",
        "prepared": "signs of meal preparation (served food, plated dishes, cooking context)",
        "exciting": "lively expressions and energetic interaction (smile, engaged body language)",
        "chat": "both characters actively talking face-to-face",
        "movie": "cinema/movie-watching context with screen glow or theater seating cues",
        "watched": "both characters watching the same screen/event together",
        "smiled": "both characters smiling with visible joyful expressions",
        "asian food": "Asian food ingredients or dishes visibly present",
        "chinese": "Chinese food products or labels as environment cues",
    }
    for k, v in mapping.items():
        if k in s:
            anchors.append(v)
    if not anchors:
        anchors.append("environment must clearly reflect the sentence context and actions")
    return anchors[:5]


def _build_strict_environment_lock(sentence: str) -> str:
    s = sentence.lower()
    rules: list[str] = []

    rules.append("Primary location must be clearly visible in frame; do NOT output a portrait-only close-up.")

    if "forest" in s:
        rules.append("Primary location must be a forest (trees/woods clearly visible).")
        rules.append("Forest environment should dominate the frame (at least 60 percent of visible background).")
        rules.append("Use an establishing outdoor composition so forest depth is obvious.")
    if "downtown" in s and ("far away" in s or "away from downtown" in s):
        rules.append("The scene must show that it is far from downtown (no central city street setting).")
        rules.append("If city appears, it must be distant in the background (e.g., tiny skyline on horizon), not the main location.")
        rules.append("Forbidden main background elements: dense urban buildings, indoor restaurant, office interior.")
    if "supermarket" in s:
        rules.append("Primary location must be inside a supermarket with visible aisles/shelves.")
    if ("bus" in s) or ("got off the bus" in s) or ("get off the bus" in s):
        rules.append("Primary location must include a bus stop/roadside transit context with visible bus, bus door, or bus stop sign.")
        rules.append("The action must show both characters after getting off the bus and continuing on foot together.")
        rules.append("Both leads should be walking side by side (not standing still portrait pose).")
        rules.append("Forbidden main location: indoor room, restaurant interior, generic studio backdrop.")
    if "coffee" in s or "cafe" in s:
        rules.append("Primary location must include coffee context (cafe table/cups/mugs clearly visible).")
        rules.append("Both leads must be together at the same table or cafe area, interacting while drinking or holding coffee.")
        rules.append("Forbidden main location: random street/forest scene without any coffee evidence.")
    if "chat" in s or "chatted" in s:
        rules.append("The image must show two-way conversation cues (facing each other, engaged eye contact, expressive posture).")
    if "date" in s:
        rules.append("The composition should clearly read as a date moment with both leads present and interacting.")
    if "kitchen" in s or "cook" in s:
        rules.append("Kitchen/home cooking environment must be visible (counter/ingredients/tools).")
    if "warm" in s:
        rules.append("Weather/mood must visually feel warm outdoors (sunlit tone, pleasant warm atmosphere).")
    if "dinner" in s or "restaurant" in s or "eat" in s:
        rules.append("Primary location MUST be a restaurant interior or dining room.")
        rules.append("A dining table with visible food, plates, and cutlery MUST be in the frame.")
        rules.append("Both characters must be seated at or closely interacting with the dining table.")
        rules.append("Forbidden main location: outdoor street, daytime sunlight, standing in a hallway, empty room without a table.")
        rules.append("Forbidden: portrait-only close-up with no table or food; the dining context must be clearly visible.")
    if "dinner" in s and ("meet him" in s or "to meet him" in s or "met him" in s or ("exciting" in s and " him" in s)):
        rules.append(
            "ONLY two people at dinner: the female protagonist and the single male date she is meeting. "
            "Forbidden: third person at the table, three-person composition, love-triangle dinner, two women with one man."
        )
    if "prepared" in s and "dinner" in s:
        rules.append("The image must imply dinner was prepared (served dishes or active serving action).")
    if "exciting" in s:
        rules.append("Characters MUST show lively, energetic mood: visible happy or excited expressions, engaged eye contact or smiles; forbidden: blank neutral stare, contemplative gaze away from each other, emotionless faces.")
    if "invited" in s or "invitation" in s:
        rules.append("Scene must read as a shared social moment (date/invitation context) with both characters present and interacting.")
    if "movie" in s or "watched" in s:
        rules.append("Primary location must show movie-watching context (cinema/theater/home movie setup with visible screen light).")
        rules.append("Both leads should be oriented toward the same movie context while still visible to camera.")
    if "smile" in s or "smiled" in s:
        rules.append("Both leads should have visible smiling expressions.")
    if "beach" in s:
        rules.append("Primary location must be a beach/seaside with sea/shore visible.")
    if "park" in s:
        rules.append("Primary location must be a park/green public outdoor space.")
    if "forest" in s:
        rules.append("Forbidden main location: candlelight indoor restaurant/date-table scene.")
    if ("moment" in s and "him" in s) or ("sweet" in s and "moment" in s) or ("shared" in s and "moment" in s and "him" in s):
        rules.append(
            "Exactly ONE man (date) and ONE woman in frame; male lead must be as visually clear as the female protagonist — not cropped, not tiny."
        )
        rules.append(
            "Mood: tender sweet shared moment — warm relaxed genuine smiles; forbidden: three faces, two women flanking, triptych."
        )
        if "nervous" in s and "but" in s:
            rules.append(
                "User wrote contrast (e.g. nervous but sweet): depict ONLY the sweet warm part in facial expressions, not anxiety."
            )

    rules.append("Do not age-up faces; both leads should look like youthful adults in the 20-39 range.")
    return " ".join(rules)


async def _validate_two_character_image(*args, **kwargs):
    return True


def _dedupe_models_used(names: list[str]) -> list[str]:
    return list(dict.fromkeys(names))


async def _sentence_to_structured_scene(
    client: AsyncOpenAI,
    sentence: str,
    scene: str,
    story_mode: str,
    required_words: list[str],
    model_trace: list[str] | None = None,
):
    system_prompt = f"""
You are a master storyboard artist and prompt-compiler for a text-to-image AI (SDXL).
The image AI CANNOT understand abstract events (like "dinner", "date", "party"). It ONLY understands exact physical places, objects, and lighting.
The image AI CANNOT understand NEGATION: it will latch onto the word "nervous" even if you write "don't feel nervous", and draw a nervous person.

CRITICAL RULE FOR EMOTION EXTRACTION (IRON LAW — applies to EVERY JSON you output):
1. Ignore negative grammar literally. You MUST translate the TRUE visual emotion the viewer should SEE — not what the user linguistically denied.
2. If the user writes "don't feel nervous", "not tense", "not worried" — DO NOT output "nervous", "tense", or "worried" in 'emotion'. You MUST output the visual opposite: relaxed expression, calm, comfortable, smiling joyfully, confident soft gaze, at ease.
3. If the user writes "not sad", "don't feel down", "won't cry", "no tears" — DO NOT output "sad", "crying", "tears", or "tearful". You MUST output: happy peaceful face, gentle genuine smile, bright eyes, content mood, dry eyes.
4. Always provide POSITIVE visual cues only. The 'emotion' field must read like a brief for a romance film still — never a list of negated feelings, never words that would make SDXL paint the wrong face.
5. Default when ambiguous: both leads look warm, photogenic, approachable — forbid implying grotesque expressions, random crying, twisted grimace, or angry scowl unless the user clearly wants that exact negative mood.
6. BUT-CLAUSE WINS: If the user writes "I feel nervous BUT we shared a sweet moment" or "nervous but ... sweet / happy / relaxed / moment with him", the FIRST part is internal feeling — the IMAGE must show ONLY the SECOND part. Output emotion for the sweet/warm/tender moment: soft smiles, warm eye contact, romantic gentle mood. NEVER put "nervous", "anxious", "worried", or "tense" in the 'emotion' field when "but" introduces a positive shared moment. The scene is still exactly ONE MAN (the date) and ONE WOMAN (protagonist) sharing that moment — never three people, never two women without the man clearly visible.

CRITICAL RULES (scene/location):
1) SWEET MOMENT WITH HIM: If the sentence contains "sweet moment", "moment with him", or "shared ... moment" with "him", set 'emotion' to "tender warm connection, soft happy smiles, intimate sweet date glow, relaxed joy — NOT nervous, NOT anxious". Set 'core_action' to "male lead and female protagonist sharing a close sweet moment, facing each other or shoulder to shoulder, man clearly visible". Add to 'must_show': "exactly one man and one woman, male date in frame, no third person". Add to 'forbidden': "nervous face, anxious expression, three people, two women without man, triptych".
1b) DINNER + MEET HIM: If "dinner" appears with "meet him", "to meet him", "met him", or "exciting" + "him", the scene is ONLY the female protagonist and the ONE male lead at dinner — a table for two. Add to 'must_show': "only two place settings, two diners, male date clearly visible". Add to 'forbidden': "third guest, three people at table, love triangle dinner, two women with one man, group dinner". Emotion: excited happy first-meeting smiles.
2) MEALS = RESTAURANT & TABLE (Crucial): If the sentence contains words like "dinner", "lunch", "breakfast", or "eat", you MUST set the 'location' to "an upscale restaurant interior" or "a cozy dining room". You MUST add "a dining table with plated food, wine glasses, and cutlery" to both 'environment_details' and 'must_show'.
3) TIME TO LIGHTING: "dinner" means the 'lighting' MUST be "evening, warm indoor restaurant lighting, candlelight". It MUST NOT be daylight or outdoor sunlight.
4) ABSTRACT TO PROPS: If you see abstract adjectives ("funny", "exciting"), invent physical evidence. "funny" -> "amused, smiling or laughing; lighthearted". "exciting" -> "dynamic pose, wide expressive smiles".
5) PARK = OUTDOOR PARK: If the sentence contains "park", you MUST set 'location' to "a park with trees, walking paths, green lawn or grass" and add to 'environment_details' and 'must_show': "outdoor park, trees visible, path or green space". Set 'lighting' to "daylight, natural outdoor, soft sun". Add to 'forbidden': "indoor room, plain wall, studio backdrop, no trees".
6) WALK = WALKING POSE: If the sentence contains "walk", "walked", or "walking", set 'core_action' to include "walking together in the park" (or location) and add to 'must_show': "both characters walking or in walking pose, side by side".
7) FUNNY STORIES = LAUGHING: If the sentence contains "funny" (e.g. "funny stories"), set 'emotion' to "amused, smiling or laughing; lighthearted; sharing a laugh; both characters look happy and engaged" and add to 'must_show': "both characters smiling or laughing".
8) SURPRISE (positive, e.g. "it's a surprise that we have so much in common"): Set 'emotion' to include "pleasant surprise, delighted, warm connection; happy surprised expression" and add to 'must_show': "warm delighted expressions; connection". Do NOT use "shocked" or "scared" — use "delighted surprise".
9) KISS: If the sentence contains "kiss", "kissed", or "kissing", you MUST set 'core_action' to "romantic kiss, lips touching or about to kiss, tender intimate moment" and add to 'must_show': "both characters kissing, lips touching or very close, romantic kiss moment". Location can be outdoor or as described (e.g. "in the rain").
10) RAIN: If the sentence contains "rain", "raining", or "rainy", you MUST set 'location' to include "rainy outdoor" or "in the rain", 'lighting' to "rainy overcast, raindrops visible", and add to 'must_show': "rain, raindrops visible, wet hair or wet surfaces, rainy atmosphere". Add to 'forbidden': "dry, sunny, no rain".
11) CHAT = TWO-PERSON TALK (NOT THREE FACES): If the sentence contains "chat", "chatted", "talking", "talk", or "conversation", set 'location' to a clear two-person spot UNLESS "dinner" is also in the sentence — then location MUST be "restaurant interior with dinner table, plates, and food", not a generic cafe. Set 'core_action' to "man and woman talking face-to-face in ONE continuous shot" (at dinner table if dinner). Add to 'must_show': "only two people visible". Add to 'forbidden': "triptych, three faces, face-only portrait with no table when dinner is mentioned".
12) EXCITING = LIVELY FACE: If the sentence contains "exciting", set 'emotion' to "excited, happy, wide smiles or animated expressions; lively energy" — never "neutral", "calm", or "contemplative". If the sentence also contains "chat" or "dinner", set 'emotion' to "excited, happy, lively; visible smiles and animated expressions; exciting conversation or dinner vibe" and add to 'must_show': "both characters with happy excited expressions".
13) DATE SCENE = ONE MAN + ONE WOMAN: Every scene is a date between the MALE LEAD and the FEMALE protagonist. Never output or imply two women or two men. The image must show one man (the date) and one woman (the user). Add to 'forbidden': "two women, two girls, only females in frame".
14) EXACTLY TWO PEOPLE ONE FRAME: Never three+ people. Never triptych, three faces in a row, character lineup, or reference sheet. Set 'camera' to a single two-shot (e.g. "medium two-shot, one continuous scene") not "three panels". Add to 'forbidden': "third person, triptych, three portraits side by side, group of three".
15) ENJOY / RELAXED / NOT NERVOUS: If the sentence contains "enjoy", "comfortable", "relaxed", "nervous" (e.g. "don't feel nervous"), "moment with him", or "happy", you MUST set 'emotion' to "relaxed, happy, enjoying the moment; warm genuine smiles; comfortable and at ease; BOTH characters must look content and positive" and add to 'forbidden': "surprised expression, worried look, tense face, anxious expression, wide-eyed shock". If the sentence also has "but" + sweet/moment with him, prefer rule 1) and 5) — never "nervous" in emotion.
16) Keep required words semantically present: {required_words}
17) CALL/TEXT/SOLO MALE SHOTS: If the sentence involves phone, call, text, or message, the visual focus may be the male lead alone. Emotion MUST still use positive visual translation: e.g. "I don't feel nervous" / "not nervous" → relaxed, comfortable, confident smile — NEVER put "nervous", "tense", or "anxious" in emotion. "I won't cry" → calm, content, soft smile — NEVER "crying" or "tearful".

Return ONLY JSON matching this structure perfectly:
{{
  "core_action": "(Frozen physical pose, e.g., 'sitting at a table talking')",
  "location": "(Exact physical place, e.g., 'fine dining restaurant interior')",
  "environment_details": [
    "(Visual proof of context, e.g., 'table set with plates and food')",
    "(Lighting/Vibe details)"
  ],
  "lighting": "(Specific lighting, e.g., 'warm evening restaurant lighting')",
  "emotion": "(Exaggerated visible facial expressions)",
  "camera": "(Shot size)",
  "must_show": ["(List of physical objects, MUST include table/food if it's a dinner scene)"],
  "forbidden": ["(Things that ruin the context, e.g., 'outdoor street, broad daylight' for dinner)"]
}}
"""
    user_text = f"scene={scene}; mode={story_mode}; sentence={sentence}"
    try:
        resp = await _openrouter_chat(
            client,
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            response_format={"type": "json_object"},
            _model_trace=model_trace,
        )
        data = json.loads(resp.choices[0].message.content)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print(f"⚠️ structured middleware fallback: {str(e)}")

    return {
        "core_action": sentence,
        "location": scene,
        "environment_details": ["context follows sentence literally"],
        "lighting": "cinematic natural lighting",
        "emotion": "engaged interaction",
        "camera": "medium-wide two shot",
        "must_show": required_words[:],
        "forbidden": [],
    }


def _compose_prompt_from_structured(
    style_prefix: str,
    request: ProcessTurnRequest,
    male_appearance: str,
    male_identity_lock: str,
    protagonist_identity_lock: str,
    scene_anchors: list[str],
    strict_env_lock: str,
    shot_directive: str,
    structured: dict[str, Any],
):
    core_action = structured.get("core_action", request.sentence)
    location = structured.get("location", request.scene)
    env_details_list = structured.get("environment_details") or []
    env_details = ", ".join(env_details_list) if env_details_list else ""

    # 语义锁：图像必须与玩家输入的句子严格对齐，表情不能与句意相反
    emotion_rule = (
        "Facial expressions MUST match the sentence mood: if the sentence says enjoy, relaxed, or not nervous, "
        "both characters must look relaxed and happy with warm smiles; never surprised, worried, or tense. "
    )
    semantic_lock = (
        f'STRICT SEMANTIC LOCK: This image MUST depict exactly this moment (literal scene, no deviation): "{request.sentence}". '
        "The scene, setting, and character emotions must match the sentence meaning. "
        f"{emotion_rule}"
        "MAIN SUBJECT MUST BE HUMANS: at least two clearly visible human faces and bodies; "
        "FORBIDDEN as main subject: coffee table books, open magazines, catalogs, brochures, product still life, "
        "furniture catalog photos, empty rooms with no people, objects-only composition. "
    )

    return (
        f"{TWO_SHOT_CAMERA_DIRECTIVE}"
        f"{semantic_lock}"
        f"Strictly only two people: exactly 1boy and 1girl, no one else. No second man, no two men, no two women. The man (male lead) and the woman (protagonist) must BOTH be clearly visible in frame. "
        f"EXACTLY two people only: the male lead and the female protagonist. This is a date scene: one man and one woman. The MALE LEAD (man) must be clearly visible in frame—do not crop him out; do not show two women. Forbidden: two women, two girls, only females. "
        f"Cinematic split shot. Male lead on the LEFT, Female on the RIGHT. "
        f"{style_prefix}. "
        f"A cinematic wide two-shot. Exactly two distinct people interacting in the same frame: one woman and one man. "
        f"Hands relaxed at sides or naturally placed; natural arm proportions; focus on faces and upper body; avoid prominent hand gestures in center of frame. "
        f"LEFT SIDE: the man {request.character} ({male_appearance}, {male_identity_lock}). "
        f"RIGHT SIDE: the woman — protagonist ({request.protagonist_profile}, {protagonist_identity_lock}). "
        f"The woman must look exactly like the described protagonist; do not generate a generic different face. "
        f"Age lock: all main characters must look like adults between 20 and 39 years old; no middle-aged/elderly appearance. "
        f"Action: {core_action}. "
        f"Setting: {location}, {env_details}. "
        f"Atmosphere is {structured.get('emotion', 'engaged interaction')} in a {structured.get('lighting', 'cinematic warm halo lighting')} ambiance. "
        f"Environment lock (strict): include these visual anchors: {', '.join(scene_anchors)}. "
        f"Environment rules (strict): {strict_env_lock}. "
        f"{shot_directive} "
        f"safe, non-explicit."
    )


def _fallback_words(word_count: int, recent_words: list[str]):
    verbs = ["walk", "call", "share", "plan", "cook", "visit", "help", "smile", "choose", "wait"]
    nouns = ["friend", "coffee", "bus", "home", "music", "book", "market", "phone", "street", "class"]
    adjs = ["easy", "busy", "happy", "quiet", "useful", "kind", "fresh", "simple", "warm", "bright"]

    recent_set = {w.lower() for w in recent_words}
    random.shuffle(verbs)
    random.shuffle(nouns)
    random.shuffle(adjs)

    picks = []
    for bucket in (verbs, nouns, adjs):
        for w in bucket:
            if w.lower() not in recent_set and w.lower() not in {x.lower() for x in picks}:
                picks.append(w)
                break

    pool = verbs + nouns + adjs
    random.shuffle(pool)
    for w in pool:
        if len(picks) >= word_count:
            break
        if w.lower() in recent_set or w.lower() in {x.lower() for x in picks}:
            continue
        picks.append(w)

    out = {"words": picks[:word_count], "text_models_used": []}
    return out


@app.post("/api/get_words")
async def get_words(request: GetWordsRequest):
    client = get_async_openai_client()
    model_trace: list[str] = []
    try:
        print(f"👉 收到前端请求：场景[{request.scene}]，要求生成 【{request.word_count}】 个词！")
        
        recent = request.recent_words[-40:] if request.recent_words else []
        prompt = f"""
You are a friendly English tutor for middle-school learners (A2-B1).

CONTEXT:
- Story mode: {request.story_mode}
- Scene tag: {request.scene} (do not overfit to romance; choose general everyday-life words)
- Character: {request.character} (only a flavor; words must be broadly useful)

RULES:
- Return EXACTLY {request.word_count} items in JSON: {{ "words": ["...", "..."] }}.
- Words must be common, practical, everyday-life vocabulary (work/school/travel/social/daily routines).
- Difficulty: middle-school friendly; avoid rare idioms and advanced academic words.
- Variety: Across the list, include at least 1 verb, 1 noun, and 1 adjective.
- Avoid repeating any of these recent words (case-insensitive): {recent}
- Avoid overly romantic/sexual words.

FORMAT:
Return ONLY valid JSON with key "words".
"""
        
        def _normalize_words(payload: dict) -> list[str]:
            words = payload.get("words") or []
            normalized: list[str] = []
            for w in words:
                if isinstance(w, str):
                    normalized.append(w.strip())
                elif isinstance(w, dict) and isinstance(w.get("word"), str):
                    normalized.append(w["word"].strip())
            out: list[str] = []
            seen = set()
            for w in normalized:
                if not w:
                    continue
                key = w.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(w)
            return out

        avoid_set = {w.lower() for w in recent}
        last_data = None
        for attempt in range(3):
            resp = await asyncio.wait_for(
                _openrouter_chat(
                    client,
                    model=CHAT_MODEL,
                    messages=[{"role": "system", "content": prompt}],
                    response_format={"type": "json_object"},
                    _model_trace=model_trace,
                ),
                timeout=12.0,
            )
            last_data = json.loads(resp.choices[0].message.content)
            words = _normalize_words(last_data)

            if len(words) != request.word_count:
                continue
            if any(w.lower() in avoid_set for w in words):
                avoid_set.update([w.lower() for w in words])
                prompt = prompt.replace(f"{recent}", f"{sorted(list(avoid_set))[-40:]}")
                continue

            return {"words": words, "text_models_used": _dedupe_models_used(model_trace)}

        if last_data is not None:
            words = _normalize_words(last_data)
            if len(words) >= request.word_count:
                return {
                    "words": words[: request.word_count],
                    "text_models_used": _dedupe_models_used(model_trace),
                }
        out = _fallback_words(request.word_count, request.recent_words)
        out["text_models_used"] = _dedupe_models_used(model_trace)
        return out
    except Exception as e:
        print(f"❌ OpenRouter 报错: {str(e)}")
        out = _fallback_words(request.word_count, request.recent_words)
        out["text_models_used"] = _dedupe_models_used(model_trace)
        return out
    finally:
        await client.close()


@app.post("/api/get_storyline")
async def get_storyline(request: FinalStoryRequest):
    try:
        return {"status": "success", "storyline": _build_storyline(request.scene, request.character, request.story_mode)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/process_turn")
async def process_turn(request: ProcessTurnRequest):
    client = get_async_openai_client()
    model_trace: list[str] = []
    try:
        # Python 强拦截：必须使用本轮全部选词，不交给 LLM 做“数数”（省 API 且 100% 准确）
        missing_words = [w for w in request.required_words if not _contains_word_family(request.sentence, w)]
        if missing_words:
            check_result = {
                "is_correct": False,
                "failure_kind": "missing_required_words",
                "feedback": (
                    f"本轮必须出现全部「命运词」才算通过。你还缺少: {', '.join(missing_words)}。"
                    f"完整要求: {', '.join(request.required_words)}。"
                    "请把这些词自然地写进句子里再提交（这不是语法错误，也不会显示「修正句」）。"
                ),
                # 故意不传「修正句」：缺词时无语法修正，避免前端误显示「仅语法最小修正」却和原句一模一样
                "corrected_sentence": None,
            }
            return {"status": "failed", "check_result": check_result, "image_url": None, "text_models_used": []}

        check_result = {
            "is_correct": True,
            "failure_kind": None,
            "feedback": "Sentence accepted.",
            "corrected_sentence": request.sentence,
        }
        check_prompt = f"""
You are validating English for a game. The user has already used all required words (checked separately). Your job is STRICT and narrow.

User sentence (respect their wording and emotional intent — do NOT "improve" style or paraphrase):
"{request.sentence}"
Required words (already satisfied): {request.required_words}
Scene: {request.scene}

WHAT COUNTS AS "is_correct": false (FAIL) — ONLY objective grammar/syntax errors, for example:
- Clear subject-verb disagreement ("he go" → must be "goes")
- Wrong inflection or word form that is incorrect in standard English ("I goed")
- Broken sentence structure that is not a valid English sentence
- Wrong article or preposition ONLY when it makes the sentence clearly ungrammatical (not when two prepositions are both acceptable)

WHAT MUST ALWAYS BE "is_correct": true (PASS):
- The sentence is understandable and grammatically acceptable, even if unusual, poetic, or not how a native speaker would say it
- Unusual collocations, strong emotion, implied meaning, or "non-textbook" phrasing chosen on purpose
- Stylistic or pragmatic choices (e.g. who "laughs at" vs "with" — NEVER fail for interpretation or tone)
- Slightly awkward but still grammatical English

FORBIDDEN:
- Do NOT fail because you would phrase it differently or find it "unnatural"
- Do NOT suggest alternative sentences for style, clarity, or "better" English in feedback
- Do NOT change the user's emotional content or story in "corrected_sentence"

"feedback" field:
- If PASS: short warm praise in mixed Chinese + English only (e.g. "🌟 Nice! 已通过。"). No alternative wording.
- If FAIL: explain ONLY the specific grammar rule violated in mixed Chinese + English. No full rewrite in feedback.

"corrected_sentence" field:
- If PASS: copy the user's sentence EXACTLY as given (character-for-character identical to the input sentence).
- If FAIL: give the MINIMAL edit that fixes ONLY the grammar error; keep meaning and tone; keep all required words (same word families).

If you are unsure whether it is a grammar error, choose "is_correct": true.

Return ONLY valid JSON:
{{ "is_correct": true/false, "feedback": "...", "corrected_sentence": "..." }}
"""
        try:
            resp = await _openrouter_chat(
                client,
                model=CHAT_MODEL,
                messages=[{"role": "system", "content": check_prompt}],
                response_format={"type": "json_object"},
                _model_trace=model_trace,
            )
            check_result = json.loads(resp.choices[0].message.content)
            # 用户要求：通过时不得「纠正」表达或情感，展示句必须与原句一致
            if check_result.get("is_correct") is True:
                check_result["corrected_sentence"] = request.sentence
            check_result["failure_kind"] = None if check_result.get("is_correct") else "grammar"
        except Exception as grammar_err:
            msg = str(grammar_err)
            if _is_openrouter_credit_issue(msg):
                print(f"⚠️ grammar check fallback due to OpenRouter credits: {msg}")
                check_result = {
                    "is_correct": True,
                    "failure_kind": None,
                    "feedback": "Grammar check is temporarily skipped due to service credit limits. You can continue.",
                    "corrected_sentence": request.sentence,
                }
            else:
                raise

        corrected = check_result.get("corrected_sentence")
        if isinstance(corrected, str) and corrected.strip():
            replaced_required = any(
                not _contains_word_family(corrected, w) for w in request.required_words
            )
            if replaced_required:
                check_result["corrected_sentence"] = request.sentence
                if check_result.get("is_correct") is False:
                    check_result["is_correct"] = True
                original_feedback = check_result.get("feedback", "")
                check_result["feedback"] = original_feedback
        if check_result.get("is_correct"):
            check_result["failure_kind"] = None

        if not check_result.get("is_correct"):
            return {
                "status": "failed",
                "check_result": check_result,
                "image_url": None,
                "text_models_used": _dedupe_models_used(model_trace),
            }

        try:
            _pstyle = (request.portrait_style or "cinematic").strip().lower()
            if _pstyle == "comic":
                style_prefix = COMIC_STYLE_PRESETS.get(request.story_style, COMIC_STYLE_PRESETS["mature_romantic"])
            else:
                style_prefix = STYLE_PRESETS.get(request.story_style, STYLE_PRESETS["mature_romantic"])
            male_appearance = _character_appearance(request.character)
            male_negative = _character_negative(request.character)
            male_identity_lock = _character_identity_lock(request.character)
            protagonist_identity_lock = (
                f"protagonist must strictly match this selected look: {request.protagonist_profile}; "
                "keep consistent facial structure, hairstyle, and vibe; do not switch to another woman."
            )
            scene_anchors = _extract_scene_anchors(request.sentence)
            strict_env_lock = _build_strict_environment_lock(request.sentence)
            sentence_lower = request.sentence.lower()
            is_forest_sentence = "forest" in sentence_lower
            is_dinner_sentence = "dinner" in sentence_lower
            # 「餐厅」与「晚餐」在画面上同为餐桌约会场景；仅写 restaurant 未写 dinner 时也必须锁双人+餐桌
            is_restaurant_sentence = "restaurant" in sentence_lower or "bistro" in sentence_lower
            is_dinner_or_restaurant = is_dinner_sentence or is_restaurant_sentence
            is_movie_sentence = ("movie" in sentence_lower) or ("watched" in sentence_lower)
            is_bus_sentence = ("bus" in sentence_lower) or ("got off the bus" in sentence_lower) or ("get off the bus" in sentence_lower)
            is_coffee_sentence = ("coffee" in sentence_lower) or ("cafe" in sentence_lower)
            is_exciting_sentence = "exciting" in sentence_lower
            is_chat_sentence = ("chat" in sentence_lower) or ("chatted" in sentence_lower) or ("talking" in sentence_lower) or ("talk" in sentence_lower)
            is_friend_sentence = "friend" in sentence_lower or "friends" in sentence_lower
            # 语义：句子表达享受/不紧张/和“他”的 moment → 图里必须放松开心，不能惊讶担忧
            is_enjoy_relax_sentence = any(
                w in sentence_lower for w in ["enjoy", "nervous", "relax", "comfortable", "moment with him", "happy with"]
            )
            # 通讯场景：call/phone/message/text → 不强制两人同框，只画男主单人拿电话对你笑
            is_phone_scene = any(
                w in sentence_lower for w in ["call", "phone", "message", "text", "texted", "texting", "called", "calling"]
            )
            is_park_sentence = "park" in sentence_lower
            is_walk_sentence = any(w in sentence_lower for w in ["walk", "walked", "walking"])
            is_funny_sentence = "funny" in sentence_lower
            is_surprise_sentence = "surprise" in sentence_lower
            is_kiss_sentence = any(w in sentence_lower for w in ["kiss", "kissed", "kissing"])
            is_rain_sentence = any(w in sentence_lower for w in ["rain", "raining", "rainy"])
            # 「和他甜蜜瞬间 / shared sweet moment」——画面只能是温馨双人，禁止紧张脸、禁止第三人/双女主
            is_sweet_moment_with_him = (
                ("sweet" in sentence_lower and "moment" in sentence_lower)
                or ("moment" in sentence_lower and "with him" in sentence_lower)
                or ("shared" in sentence_lower and "moment" in sentence_lower and "him" in sentence_lower)
            )
            # 晚餐/餐厅 + 见他：语义是「两人约会就餐」，不是三人同桌、不是三角关系构图
            is_dinner_meet_him = is_dinner_or_restaurant and (
                "meet him" in sentence_lower
                or "met him" in sentence_lower
                or "met me" in sentence_lower
                or "to meet him" in sentence_lower
                or ("exciting" in sentence_lower and " him" in sentence_lower)
                or ("excited" in sentence_lower and (" him" in sentence_lower or " met me" in sentence_lower or " at " in sentence_lower))
            )
            shot_directive = (
                "Use a medium romantic two-shot: EXACTLY one man (male date) and one woman (protagonist) in ONE frame. "
                "They are sharing a tender sweet moment — soft warm genuine smiles, gentle eye contact, cozy golden or candlelight mood. "
                "The MAN must be clearly visible (face + upper body), not cropped or hidden. "
                "Forbidden in this shot: nervous or anxious expressions, third person, two women without the man, triptych."
                if is_sweet_moment_with_him
                else (
                    "Use a medium-wide restaurant dinner shot: EXACTLY TWO people total — the woman (protagonist) and the ONE man (her date). "
                    "They share ONE table for two: visible plates, food, wine or water glasses, warm restaurant candlelight. "
                    "Both seated across or beside each other at the same small table. "
                    "FORBIDDEN: third diner, third chair occupied, three faces, love-triangle trio, group dinner, two women with one man ambiguous framing. "
                    "Excited happy 'first time meeting him' smiles — still only these two in frame."
                    if is_dinner_meet_him
                    else None
                )
            )
            if shot_directive is None:
                shot_directive = (
                "Use a wide establishing shot (not close-up) so the forest environment is unmistakable."
                if is_forest_sentence
                else (
                    "Use a medium-wide shot that clearly shows dinner table and food context."
                    if is_dinner_or_restaurant
                    else (
                        "Use a cinematic waist-up two-shot (both characters side by side) with visible movie-screen light in background."
                        if is_movie_sentence
                        else (
                            "Use a wide street-level shot with a visible bus stop/bus cue and both characters walking together after getting off the bus."
                            if is_bus_sentence
                            else (
                                "Use a medium-wide two-shot in a cafe/date setting with clearly visible coffee cups and conversation body language."
                                if is_coffee_sentence
                                else (
                                    "Use a wide or medium shot showing park (trees, path, green space), both characters walking or standing in the park, outdoor daylight."
                                    if is_park_sentence
                                    else (
                                        (
                                            "Use a close two-shot, both characters kissing in the rain, lips touching or about to kiss, visible raindrops, wet hair or wet surfaces, romantic kiss in rain."
                                            if is_rain_sentence
                                            else "Use a close two-shot, both characters in a romantic kiss, lips touching or about to kiss, tender moment."
                                        )
                                        if is_kiss_sentence
                                        else (
                                            "Use a medium two-shot with both characters clearly in conversation: facing each other, expressive faces, conversational gestures (e.g. hands, leaning in)."
                                            if is_chat_sentence
                                            else "Use a medium or wide shot so environment context is obvious."
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
                )
            structured = await _sentence_to_structured_scene(
                client=client,
                sentence=request.sentence,
                scene=request.scene,
                story_mode=request.story_mode,
                required_words=request.required_words,
                model_trace=model_trace,
            )
            if is_movie_sentence:
                ms = structured.get("must_show") or []
                ms.extend(["movie watching context", "both people in same shot", "screen glow"])
                structured["must_show"] = ms
            if is_bus_sentence:
                ms = structured.get("must_show") or []
                ms.extend(["bus stop or bus cue", "both characters walking together", "outdoor warm street atmosphere"])
                structured["must_show"] = ms
            if is_coffee_sentence:
                ms = structured.get("must_show") or []
                ms.extend(["coffee cups/mugs", "cafe or coffee-table context", "both characters chatting together"])
                structured["must_show"] = ms
            if is_chat_sentence:
                structured["emotion"] = "engaged, animated, clearly conversing; visible smiles or expressive faces; conversation body language"
                structured["core_action"] = structured.get("core_action") or (
                    "man and woman chatting face-to-face at a small table or cozy booth; warm friendly vibe; single camera shot, only these two people"
                )
                structured["location"] = structured.get("location") or "cozy cafe or quiet lounge with table between them"
                ms = structured.get("must_show") or []
                ms.extend(["exactly two people in frame", "no third face", "conversation across table or close seating"])
                structured["must_show"] = ms
                structured.setdefault("forbidden", [])
                if isinstance(structured["forbidden"], list):
                    structured["forbidden"] = list(structured["forbidden"]) + [
                        "triptych", "three faces in a row", "three portraits", "character roster", "lineup of heads"
                    ]
            # 语义对齐：句子有 enjoy / don't feel nervous / moment with him → 必须放松、开心、享受，不能惊讶/担忧
            if is_enjoy_relax_sentence:
                structured["emotion"] = (
                    "relaxed, happy, enjoying the moment; warm genuine smiles; both characters look content and at ease; "
                    "forbidden: surprised, worried, tense, anxious, or wide-eyed expression"
                )
                structured.setdefault("forbidden", [])
                if isinstance(structured["forbidden"], list):
                    structured["forbidden"] = list(structured["forbidden"]) + [
                        "surprised expression", "worried look", "tense face", "anxious expression", "wide-eyed shock"
                    ]
            if is_exciting_sentence:
                structured["emotion"] = "excited, happy, lively; wide smiles or animated expressions; energetic vibe"
                if not is_chat_sentence:
                    structured["core_action"] = structured.get("core_action") or "dynamic pose with excited, engaged expressions"
            if is_park_sentence:
                structured["location"] = "a park with trees, walking paths, green lawn"
                ms = structured.get("must_show") or []
                ms.extend(["outdoor park", "trees visible", "path or green space"])
                structured["must_show"] = ms
                structured.setdefault("forbidden", [])
                if isinstance(structured["forbidden"], list):
                    structured["forbidden"] = list(structured["forbidden"]) + ["indoor room", "plain wall", "no trees"]
            if is_walk_sentence:
                structured["core_action"] = structured.get("core_action") or "walking together side by side"
                ms = structured.get("must_show") or []
                ms.extend(["both characters walking or in walking pose"])
                structured["must_show"] = ms
            if is_funny_sentence:
                structured["emotion"] = "amused, smiling or laughing; lighthearted; sharing a laugh; both characters happy and engaged"
                ms = structured.get("must_show") or []
                ms.extend(["both characters smiling or laughing"])
                structured["must_show"] = ms
            if is_surprise_sentence:
                structured["emotion"] = "pleasant surprise, delighted, warm connection; happy surprised expression; both characters look warmly surprised and happy"
                ms = structured.get("must_show") or []
                ms.extend(["warm delighted expressions"])
                structured["must_show"] = ms
            if is_kiss_sentence:
                structured["core_action"] = "romantic kiss, lips touching or about to kiss, tender intimate moment"
                ms = structured.get("must_show") or []
                ms.extend(["both characters kissing", "lips touching or very close", "romantic kiss"])
                structured["must_show"] = ms
            if is_rain_sentence:
                structured["location"] = (structured.get("location") or "") + ", rainy outdoor, in the rain"
                structured["lighting"] = "rainy overcast, raindrops visible, wet atmosphere"
                ms = structured.get("must_show") or []
                ms.extend(["rain", "raindrops visible", "wet hair or wet surfaces", "rainy atmosphere"])
                structured["must_show"] = ms
                structured.setdefault("forbidden", [])
                if isinstance(structured["forbidden"], list):
                    structured["forbidden"] = list(structured["forbidden"]) + ["dry", "sunny", "no rain"]

            # nervous but sweet moment with him → 画面只呈现「甜蜜瞬间」，不画紧张脸；严格一男一女
            if is_sweet_moment_with_him or (
                "nervous" in sentence_lower and " but " in sentence_lower and "moment" in sentence_lower
            ):
                structured["emotion"] = (
                    "tender sweet shared moment: relaxed warm genuine smiles, soft happy eye contact between the couple; "
                    "intimate gentle mood; expressions show trust and warmth — NOT nervous, NOT anxious, NOT worried faces"
                )
                structured["core_action"] = (
                    "male date and female protagonist sharing a close sweet moment, facing each other or leaning together; "
                    "both faces clearly visible, man's features unmistakable beside the woman"
                )
                structured["lighting"] = structured.get("lighting") or "warm golden romantic glow, soft candlelight or sunset warmth"
                structured["location"] = structured.get("location") or "intimate quiet spot: cozy booth, rooftop dusk, or window seat"
                structured["camera"] = "medium two-shot, single frame, both leads equal prominence in frame"
                ms = list(structured.get("must_show") or [])
                for x in (
                    "exactly one man and one woman",
                    "male lead face fully visible",
                    "sweet warm expressions only",
                    "no third person",
                ):
                    if x not in ms:
                        ms.append(x)
                structured["must_show"] = ms
                structured.setdefault("forbidden", [])
                if isinstance(structured["forbidden"], list):
                    structured["forbidden"] = list(structured["forbidden"]) + [
                        "nervous expression",
                        "anxious sweaty face",
                        "two women without man",
                        "three faces",
                        "triptych",
                        "man hidden or off-frame",
                    ]

            if is_dinner_meet_him:
                structured["location"] = "fine dining restaurant interior, table for two with visible dishes and cutlery"
                structured["core_action"] = (
                    "exactly two people: woman and the one man she is meeting; seated at the same dinner table; "
                    "warm restaurant date; no third guest at the table"
                )
                structured["emotion"] = (
                    "excited happy first-meeting smiles, lively engaged expressions, warm eye contact across the table; "
                    "clear joy of 'meeting him' — both faces bright and animated"
                )
                structured["lighting"] = structured.get("lighting") or "evening warm restaurant candlelight, soft glow on faces"
                ms = list(structured.get("must_show") or [])
                for x in (
                    "only two diners at this table",
                    "male date face fully visible",
                    "empty third chair or no third seat in frame",
                    "food and plates on table",
                ):
                    if x not in ms:
                        ms.append(x)
                structured["must_show"] = ms
                structured.setdefault("forbidden", [])
                if isinstance(structured["forbidden"], list):
                    structured["forbidden"] = list(structured["forbidden"]) + [
                        "third person at dinner",
                        "three people dining",
                        "love triangle trio",
                        "two women one man at table",
                        "group dinner party",
                        "ambiguous third face",
                    ]

            # 只要句子里有 dinner 或 restaurant：画面必须是「餐厅+餐桌+饭菜」——覆盖 chat→咖啡厅、PhotoMaker 大头贴
            if is_dinner_or_restaurant and not is_forest_sentence and not is_phone_scene:
                structured["location"] = (
                    "upscale restaurant interior during dinner, white or dark linen table, full place settings, warm ambient lighting"
                )
                structured["camera"] = (
                    "medium-wide cinematic shot: dining table with plated food and glasses fills lower or central frame; "
                    "both man and woman seated at this same table, waist-up or chest-up; NOT extreme facial close-up without table"
                )
                structured["core_action"] = (
                    "male date and female protagonist seated at dinner table conversing over meal; "
                    "visible dishes, cutlery, glasses on table between them; friendly engaged dinner talk"
                )
                structured["lighting"] = "warm evening restaurant lighting, candlelight or soft lamps on table"
                if "conversation" in sentence_lower or "chat" in sentence_lower or "talk" in sentence_lower:
                    structured["emotion"] = (
                        "warm friendly smiles, animated enjoyable conversation while dining; relaxed happy dinner vibe"
                    )
                ms = list(structured.get("must_show") or [])
                for x in (
                    "dining table with food clearly visible",
                    "plates and wine or water glasses on table",
                    "both seated at same dinner table",
                    "restaurant interior recognizable",
                ):
                    if x not in ms:
                        ms.append(x)
                structured["must_show"] = ms
                structured.setdefault("forbidden", [])
                if isinstance(structured["forbidden"], list):
                    structured["forbidden"] = list(structured["forbidden"]) + [
                        "face-only crop with no table in frame",
                        "extreme close-up eyes or forehead only",
                        "empty table or no dishes",
                        "cafe coffee shop without dinner plates",
                        "standing away from any dinner table",
                    ]

            art_prompt = _compose_prompt_from_structured(
                style_prefix=style_prefix,
                request=request,
                male_appearance=male_appearance,
                male_identity_lock=male_identity_lock,
                protagonist_identity_lock=protagonist_identity_lock,
                scene_anchors=scene_anchors,
                strict_env_lock=strict_env_lock,
                shot_directive=shot_directive,
                structured=structured,
            )
            if is_dinner_or_restaurant and not is_phone_scene:
                art_prompt = (
                    "PRIMARY REQUIREMENT — DINNER VISIBLE: restaurant scene with dining table, plated food, glasses; "
                    "two people at that table. The meal setting must be obvious, not an abstract face portrait. "
                    + art_prompt
                )
            seed = abs(
                hash(
                    f"{request.scene}|{request.character}|{request.story_style}|"
                    f"{request.protagonist_profile}|{request.sentence}|{','.join(request.required_words)}"
                )
            ) % 2_000_000_000
            _female_label = (request.protagonist_name or "").strip() or "Night Elegance"
            _scene_hint = (
                f"{structured.get('location') or request.scene or 'a romantic date'}, "
                f"{structured.get('emotion', '')}, matching the user sentence mood"
            ).strip().strip(",")
            ref_image_line = _build_ref_image_line_prompt(
                request.character,
                _female_label,
                _scene_hint,
            )
            duo_negative = (
                f"{male_negative}, {NO_TWO_MALES}, {BAD_HANDS}, {BAD_ARMS}, {ANTI_MUTATION_CURSE}, {NO_SOLO_CROP}, "
                "two women, 2 girls, two females, only women in frame, both women, female duo, no man in frame, male missing, only female characters, "
                "solo female portrait, solo male portrait, one person only, "
                "single-subject focus, isolated subject, second character missing, "
                "second character out of frame, second character only portrait, second character missing portrait, "
                "open book on table, coffee table book, magazine spread, catalog pages, interior design catalog, "
                "brochure still life, product photography without models, empty room with no people, objects-only shot, "
                "third person, extra person, third character, crowd, group of three, three people, multiple people, more than two people, "
                "triptych, three panel, three panels, three column layout, three faces in a row, three heads side by side, "
                "three portraits aligned horizontally, character selection screen, casting lineup, audition board, police lineup, "
                "mugshot strip, reference sheet three views, split image triple, collage of three faces, "
                "close-up portrait framing, extreme film grain, extreme film grain style, strong film grain, grain, freckles, skin grain, "
                "acne, strong skin blemishes, extremely realistic grain style, high realistic skin texture, high write skin texture, skin dots"
            )
            if is_movie_sentence:
                duo_negative += (
                    ", cinema audience, movie theater crowd, row of spectators, third face visible, "
                    "blurred person beside couple, extra viewer, people sitting behind in focus, group of moviegoers, "
                    "triple portrait, three silhouettes"
                )
            if is_sweet_moment_with_him:
                duo_negative += (
                    ", two women flanking, second woman beside heroine, love triangle three, "
                    "only female faces, man cropped out, tiny man in background, nervous frown, worried anxious stare, "
                    "sweating nervous, tense mouth"
                )
            # 句子里有 friend 时可能三人同桌，勿禁止「第三人」
            if is_dinner_meet_him and not is_friend_sentence:
                duo_negative += (
                    ", three people at restaurant, third guest, dinner party group, trio at table, "
                    "two women facing camera with man, ambiguous polyamory framing, crowded dining room focus on three faces, "
                    "love triangle dinner, third wheel seated"
                )
            if is_dinner_or_restaurant and not is_phone_scene:
                duo_negative += (
                    ", tight facial crop only, no dining table visible, forehead extreme close-up, "
                    "portrait lens face fill without meal context, missing food and plates"
                )

            # 乙游进阶：打电话/发短信场景 → 只画男主单人；情绪用 LLM「视觉翻译」避免否定句陷阱（如 don't nervous → 放松自信）
            if is_phone_scene:
                _vis_emotion = (structured.get("emotion") or "").strip()
                if len(_vis_emotion) > 200:
                    _vis_emotion = _vis_emotion[:200].rsplit(" ", 1)[0] + "…"
                if not _vis_emotion:
                    _vis_emotion = "relaxed, comfortable, confident, warm genuine smile"
                phone_prompt = (
                    f"{style_prefix}. Strictly only one person, single-subject composition. Exactly one man in frame, one face. "
                    f"A handsome man ({male_appearance}, {male_identity_lock}) talking on a smartphone, "
                    "holding phone to his ear or looking at phone screen, looking toward camera, "
                    f"facial expression and mood (visual translation from user line, never literal negated emotions): {_vis_emotion}. "
                    "cozy indoor lighting, cinematic portrait, soft bokeh background, natural hands. "
                )
                phone_negative = (
                    f"{male_negative}, {ANTI_MUTATION_CURSE}, {REPLICATE_NEGATIVE_EXTRA_FACES}, "
                    "2 people, two people, multiple people, woman in frame, female in frame, crowd, "
                    "second person, duo, couple, 1girl, extra faces, third face"
                )
                phone_ref = _build_ref_image_line_prompt(
                    request.character,
                    "",
                    "a cozy interior, phone call moment",
                )
                phone_url, phone_nsfw = await _sdxl_generate_image(
                    phone_prompt,
                    seed=seed,
                    extra_negative=phone_negative,
                    male_img=request.male_avatar_url or "",
                    female_img="",
                    is_adult=request.is_adult,
                    composition="solo",
                    portrait_style=request.portrait_style or "cinematic",
                    ref_image_line=phone_ref,
                    ref_male_character=request.character,
                    ref_female_name="",
                )
                _tm = _dedupe_models_used(model_trace)
                if not phone_nsfw and phone_url:
                    return {"status": "success", "check_result": check_result, "image_url": phone_url, "text_models_used": _tm}
                # 通讯场景只出单人图，没生成成功就返回无图，不走双人逻辑
                return {"status": "success", "check_result": check_result, "image_url": None, "text_models_used": _tm}

            image_url = None
            last_candidate_url = None
            nsfw_blocked = False
            attempts = 8 if (
                is_movie_sentence or is_bus_sentence or is_coffee_sentence or is_chat_sentence or is_exciting_sentence
                or is_friend_sentence or is_enjoy_relax_sentence or is_park_sentence or is_walk_sentence
                or is_funny_sentence or is_surprise_sentence or is_kiss_sentence or is_rain_sentence
                or is_sweet_moment_with_him or is_dinner_meet_him
            ) else 6
            duo_layout_variants = [
                "Both the man and the woman are clearly visible side by side.",
                "A balanced frame showing both characters, the man and the woman looking at each other.",
                "Wide angle establishing shot showing both the male lead and female protagonist in the scene.",
                "Two distinct people in the foreground, male and female interacting.",
            ]
            if is_sweet_moment_with_him:
                duo_layout_variants = [
                    "Waist-up romantic two-shot: male date and female protagonist, BOTH faces sharp and well-lit, equal frame weight, sweet tender smiles.",
                    "Close balanced two-shot: man in suit beside woman, leaning slightly toward each other, warm golden light, relaxed happy expressions.",
                    "Medium shot: couple sharing intimate moment, man's face fully visible next to hers, soft bokeh, no third person.",
                ] + duo_layout_variants
            if is_dinner_meet_him:
                duo_layout_variants = [
                    "Restaurant table for two: woman and man seated opposite each other, plates and glasses between them, both faces clear, third chair empty or absent.",
                    "Medium-wide dining shot: couple sharing dinner, man in suit woman in dress, excited smiles, only two place settings visible.",
                    "Candlelit two-top: exactly two diners, food on table, warm bokeh background with NO other diners' faces in focus.",
                ] + duo_layout_variants
            # kiss/rain 场景：把「一男一女、男主可见、（接吻）」放在 prompt 最前面，避免出双女主、无男主、无亲
            kiss_rain_prefix = ""
            if is_kiss_sentence:
                kiss_rain_prefix = (
                    "CRITICAL: Exactly ONE MAN (male lead) and ONE WOMAN (protagonist). They are kissing, lips touching or about to kiss. "
                    "The MAN must be clearly visible in frame, not cropped out. NOT two women, NOT two girls. "
                )
                if is_rain_sentence:
                    kiss_rain_prefix += "Rain, raindrops visible, wet hair or wet surfaces. "
            elif is_rain_sentence:
                kiss_rain_prefix = (
                    "CRITICAL: Exactly ONE MAN (male lead) and ONE WOMAN (protagonist). The MAN must be clearly visible in frame. NOT two women. "
                    "Rain, raindrops visible, wet hair or wet surfaces. "
                )
            # 所有双人场景统一锁「单镜头仅两人」——模型常把「聊天/友好」画成三张脸并排（triptych）
            duo_two_only_prefix = (
                "CRITICAL — ONE SCENE, TWO HUMANS ONLY: exactly ONE MAN and ONE WOMAN in a single unified photograph. "
                "FORBIDDEN LAYOUTS: triptych, three faces in a row, three-panel collage, character roster, "
                "lineup of three heads, selection UI with three portraits, split-frame triple, any third person. "
                "The whole image is ONE moment with ONLY this dating couple. "
            )
            if is_movie_sentence:
                duo_two_only_prefix += (
                    "They watch a movie together; background is empty seats or soft bokeh — NO recognizable faces behind them. "
                )
            elif is_chat_sentence:
                duo_two_only_prefix += (
                    "SEMANTICS: they are having a warm friendly chat — facing each other at a table or booth, "
                    "NOT a display of three separate people. Two bodies, two faces, one shared space. "
                )
            elif is_sweet_moment_with_him:
                duo_two_only_prefix += (
                    "SEMANTICS: tender sweet moment with HIM — one man + one woman only; man's face as visible as hers. "
                    "Warm relaxed smiles (the 'nervous' in text is NOT drawn). NO third person, NO two-women composition. "
                )
            elif is_dinner_meet_him:
                duo_two_only_prefix += (
                    "SEMANTICS: dinner together + excited to meet HIM = ONE man (the date) and ONE woman at ONE table. "
                    "NOT a trio, NOT three faces, NOT 'three-person dinner' art-house composition — classic two-top date only. "
                )
            for i in range(attempts):
                current_prompt = f"{duo_two_only_prefix}{kiss_rain_prefix}{art_prompt} {duo_layout_variants[i % len(duo_layout_variants)]}"
                current_seed = (seed + i * 7919) % 2_000_000_000

                if (is_forest_sentence or is_dinner_or_restaurant or is_movie_sentence or is_bus_sentence or
                        is_coffee_sentence or is_exciting_sentence or is_chat_sentence or is_friend_sentence or is_enjoy_relax_sentence or
                        is_park_sentence or is_walk_sentence or is_funny_sentence or is_surprise_sentence or is_kiss_sentence or is_rain_sentence
                        or is_sweet_moment_with_him or is_dinner_meet_him):
                    current_prompt = (
                        f"{current_prompt} HARD CONSTRAINT: "
                        + (
                            "background must be an outdoor forest with dense trees and natural ground; "
                            "do not generate indoor/city date scenes; "
                            if is_forest_sentence
                            else ""
                        )
                        + (
                            "DINNER MANDATORY: table with dishes/food/glasses MUST occupy visible frame area; both seated at table; "
                            "FORBIDDEN: image where only faces fill frame and zero dinner props visible; forehead-only shot; "
                            "empty table. Warm restaurant lighting; engaged or happy expressions. "
                            if is_dinner_or_restaurant
                            else ""
                        )
                        + (
                            "must show both characters in the same frame watching a movie together; "
                            "include cinema/screen-light context; "
                            "forbidden: single-person reaction shot; "
                            "MANDATORY: only TWO human faces in entire frame; forbidden: third person, third face, audience beside couple, row of viewers, three people. "
                            if is_movie_sentence
                            else ""
                        )
                        + (
                            "must show both characters after getting off a bus, walking together on a quiet street; "
                            "include bus stop/bus cue in frame; "
                            "forbidden: static standing portrait without walking action; "
                            if is_bus_sentence
                            else ""
                        )
                        + (
                            "must show coffee date context with visible cups/mugs on table and both characters actively chatting; "
                            "forbidden: no-coffee background or solo portrait without interaction; "
                            if is_coffee_sentence
                            else ""
                        )
                        + (
                            "both characters must show visible happy or excited expressions (smile, engaged look, animated face); lively mood; "
                            "forbidden: blank stare, neutral expression, serious face, contemplative gaze, emotionless or sad faces. "
                            if is_exciting_sentence
                            else ""
                        )
                        + (
                            "CHAT semantics: BOTH at same table or booth, facing each other, warm friendly expressions; "
                            "exactly TWO faces visible in entire image — forbidden: third face, three heads in a row, triptych. "
                            "Conversational body language (gestures, leaning in); "
                            "forbidden: static portrait lineup, neutral stare, three separate portraits. "
                            if is_chat_sentence
                            else ""
                        )
                        + (
                            "THIS IS A ONE-ON-ONE SCENE: exactly two people only (the male lead and the user protagonist). "
                            "Forbidden: any additional friend, extra man, extra woman, group of friends, love triangle, crowd, third or fourth person anywhere in the frame. "
                            "Background must not contain recognizable extra faces."
                            if is_friend_sentence
                            else ""
                        )
                        + (
                            "SEMANTIC MOOD: sentence describes enjoyment or comfort → both characters MUST look relaxed and happy, warm genuine smiles; "
                            "forbidden: surprised expression, worried look, wide-eyed, tense or anxious face. "
                            if is_enjoy_relax_sentence
                            else ""
                        )
                        + (
                            "SWEET MOMENT WITH HIM: exactly male date + female protagonist in one frame; tender warm relaxed smiles; "
                            "male face clearly visible (same weight as hers). If sentence said 'nervous but...sweet', draw ONLY the sweet part — "
                            "forbidden: nervous/anxious faces, two women, third face, man missing from frame. "
                            if is_sweet_moment_with_him
                            else ""
                        )
                        + (
                            "DINNER + MEET HIM: only the heroine and the ONE male date at dinner — table for two, no third guest. "
                            "Excited happy 'meeting him' mood. FORBIDDEN: three people, trio at table, ambiguous third face, two women with him. "
                            if is_dinner_meet_him
                            else ""
                        )
                        + (
                            "PARK: background MUST be outdoor park with trees, path or green space visible; both characters in park; "
                            "forbidden: indoor, plain wall, room, studio backdrop, no trees. "
                            if is_park_sentence
                            else ""
                        )
                        + (
                            "WALK: both characters walking or in walking pose, side by side; forbidden: static standing only, no walking. "
                            if is_walk_sentence
                            else ""
                        )
                        + (
                            "FUNNY: both characters must show smiling or laughing expressions; lighthearted; forbidden: neutral, serious, emotionless faces. "
                            if is_funny_sentence
                            else ""
                        )
                        + (
                            "SURPRISE (positive): warm delighted expressions, pleasant surprise; forbidden: shocked, scared, blank stare. "
                            if is_surprise_sentence
                            else ""
                        )
                        + (
                            "KISS: both characters MUST be shown kissing, lips touching or about to kiss, romantic kiss moment; forbidden: no kiss, standing apart, not touching. "
                            if is_kiss_sentence
                            else ""
                        )
                        + (
                            "RAIN: visible rain, raindrops, wet hair or wet surfaces, rainy atmosphere; forbidden: dry, sunny, no rain. "
                            if is_rain_sentence
                            else ""
                        )
                        + "exactly two people only; forbidden: third person, extra character, crowd, three people, two women, two girls. "
                        "One man (male lead) and one woman (protagonist) both clearly visible in frame. "
                        "both characters should look 20-39 years old; "
                        "no portrait-only framing; keep both characters visible."
                    )

                candidate_url, candidate_nsfw = await _sdxl_generate_image(
                    current_prompt,
                    seed=current_seed,
                    extra_negative=duo_negative,
                    male_img=request.male_avatar_url or "",
                    female_img=request.female_avatar_url or "",
                    is_adult=request.is_adult,
                    dinner_scene=is_dinner_or_restaurant,
                    portrait_style=request.portrait_style or "cinematic",
                    ref_image_line=ref_image_line,
                    ref_male_character=request.character,
                    ref_female_name=_female_label,
                )
                if candidate_nsfw:
                    nsfw_blocked = True
                    continue
                if not candidate_url:
                    continue
                last_candidate_url = candidate_url

                passed = await _validate_two_character_image(
                    client=client,
                    image_url=candidate_url,
                    sentence=request.sentence,
                    character_name=request.character,
                    male_identity_lock=male_identity_lock,
                    protagonist_profile=request.protagonist_profile,
                )
                if passed:
                    image_url = candidate_url
                    break

            # 全部失败时再试一次极简 prompt，提高出图率
            if image_url is None and not nsfw_blocked and not last_candidate_url:
                if is_dinner_or_restaurant:
                    simple_prompt = (
                        "Restaurant dinner: one man and one woman seated at a table with visible plates of food, "
                        "wine glasses, cutlery, medium-wide shot showing table and meal clearly, warm candlelight, cinematic."
                    )
                else:
                    simple_prompt = (
                        "One man and one woman in a romantic scene, cinematic lighting, "
                        "both clearly visible in frame, warm atmosphere, safe and non-explicit."
                    )
                try:
                    simple_url, simple_nsfw = await _sdxl_generate_image(
                        simple_prompt,
                        seed=(seed + 99999) % 2_000_000_000,
                        extra_negative=duo_negative,
                        male_img=request.male_avatar_url or "",
                        female_img=request.female_avatar_url or "",
                        is_adult=request.is_adult,
                        dinner_scene=is_dinner_or_restaurant,
                        portrait_style=request.portrait_style or "cinematic",
                        ref_image_line=ref_image_line,
                        ref_male_character=request.character,
                        ref_female_name=_female_label,
                    )
                    if not simple_nsfw and simple_url:
                        last_candidate_url = simple_url
                except Exception:
                    pass

            _tm = _dedupe_models_used(model_trace)
            if image_url is None and nsfw_blocked:
                return {
                    "status": "success",
                    "check_result": check_result,
                    "image_url": None,
                    "nsfw_blocked": True,
                    "error": "NSFW content detected by image model",
                    "text_models_used": _tm,
                }
            if image_url is None and last_candidate_url:
                return {
                    "status": "success",
                    "check_result": check_result,
                    "image_url": last_candidate_url,
                    "validation_failed_soft": True,
                    "error": "Best available image; may not fully match validation.",
                    "text_models_used": _tm,
                }
            if image_url is None:
                # 多轮尝试后仍无图：可能是 Replicate 超时/报错，或全部被 NSFW/校验拦截
                err_msg = (
                    "Image generation failed after multiple attempts. The service may be busy or the scene could not be rendered. Please try again or simplify the sentence."
                )
                print(f"⚠️ process_turn: no image after all attempts. nsfw_blocked={nsfw_blocked}, last_candidate_url={bool(last_candidate_url)}")
                return {
                    "status": "success",
                    "check_result": check_result,
                    "image_url": None,
                    "validation_failed": True,
                    "error": err_msg,
                    "text_models_used": _tm,
                }

            return {
                "status": "success",
                "check_result": check_result,
                "image_url": image_url,
                "text_models_used": _tm,
            }
        except Exception as img_err:
            msg = str(img_err)
            print(f"⚠️ Replicate 生图报错: {msg}")
            _tm = _dedupe_models_used(model_trace)
            if "not available in your region" in msg.lower():
                return {
                    "status": "success",
                    "check_result": check_result,
                    "image_url": None,
                    "region_blocked": True,
                    "error": "图片模型在你所在地区不可用（403 region blocked）。解决：1) 本机开代理；或 2) 把后端部署到可直连的地区（如新加坡/日本/美国），用户无需代理也可用。",
                    "text_models_used": _tm,
                }
            if "NSFW" in msg or "nsfw" in msg:
                return {
                    "status": "success",
                    "check_result": check_result,
                    "image_url": None,
                    "nsfw_blocked": True,
                    "error": "NSFW content detected by image model",
                    "text_models_used": _tm,
                }
            if ("429" in msg) or ("throttled" in msg.lower()) or ("rate limit" in msg.lower()):
                return {
                    "status": "success",
                    "check_result": check_result,
                    "image_url": None,
                    "rate_limited": True,
                    "error": (
                        "Replicate 生图暂时限流（429）。请等待约 15～60 秒后重试；若仍失败，请稍后再试或检查 Replicate 账户额度。"
                    ),
                    "text_models_used": _tm,
                }
            # 超时或 Replicate 服务异常：不返回 500，返回 200 + error，方便前端展示
            if "timed out" in msg.lower() or "timeout" in msg.lower() or "60 seconds" in msg or "45 seconds" in msg:
                return {
                    "status": "success",
                    "check_result": check_result,
                    "image_url": None,
                    "error": "Image generation timed out. Please try again in a moment.",
                    "text_models_used": _tm,
                }
            return {
                "status": "success",
                "check_result": check_result,
                "image_url": None,
                "error": "Image generation failed (service error). Please try again or simplify the sentence.",
                "text_models_used": _tm,
            }
    except Exception as e:
        msg = str(e)
        print(f"❌ API 2 报错: {msg}")
        _tm = _dedupe_models_used(model_trace)
        if _is_region_blocked(msg):
            return {
                "status": "success",
                "check_result": {
                    "is_correct": True,
                    "feedback": "文本模型在你所在地区不可用（403 region blocked）。本轮将跳过文本服务与图片生成。",
                    "corrected_sentence": request.sentence,
                },
                "image_url": None,
                "llm_region_blocked": True,
                "error": (
                    "【OpenRouter 403 地区限制】后端访问文本模型被拒（与浏览器 VPN 无关）。"
                    "本地：在 backend/.env 设置 OPENROUTER_PROXY=http://127.0.0.1:8001（改为 Clash/V2Ray 的「HTTP 代理」端口），保存并重启后端。"
                    "线上：Fly 将 primary_region 设为 sin（新加坡）后重新 deploy。"
                    "若 .env 里自定义了 CHAT_MODEL=openai/…，可改为 google/gemini-2.0-flash-001。"
                ),
                "text_models_used": _tm,
            }
        if _is_llm_connection_error(msg):
            return {
                "status": "success",
                "check_result": {
                    "is_correct": True,
                    "feedback": "连不上 OpenRouter（代理未通或端口不对）。请检查 backend/.env 的 OPENROUTER_PROXY 是否与代理软件「HTTP 代理」端口一致，并确保代理已开启后重启后端。",
                    "corrected_sentence": request.sentence,
                },
                "image_url": None,
                "llm_connection_failed": True,
                "error": "无法连接 OpenRouter。请确认代理已开，且 OPENROUTER_PROXY 端口正确（本项目示例 http://127.0.0.1:8001），保存 .env 后重启后端。",
                "text_models_used": _tm,
            }
        if _is_openrouter_auth_issue(msg):
            return {
                "status": "success",
                "check_result": {
                    "is_correct": True,
                    "feedback": "Text service authentication failed (401). Please check backend/.env API key.",
                    "corrected_sentence": request.sentence,
                },
                "image_url": None,
                "llm_auth_failed": True,
                "error": "OpenRouter authentication failed (401).",
                "text_models_used": _tm,
            }
        if _is_openrouter_credit_issue(msg):
            return {
                "status": "success",
                "check_result": {
                    "is_correct": True,
                    "feedback": "Text service credits are currently low; grammar/detail checks were skipped this round.",
                    "corrected_sentence": request.sentence,
                },
                "image_url": None,
                "llm_credit_limited": True,
                "error": "OpenRouter credits are insufficient.",
                "text_models_used": _tm,
            }
        raise HTTPException(status_code=500, detail=msg)
    finally:
        await client.close()


@app.post("/api/generate_final_story")
async def generate_final_story(request: FinalStoryRequest):
    client = get_async_openai_client()
    try:
        sentences_str = "\n".join([f"{i+1}. {s}" for i, s in enumerate(request.sentences)])
        _fs_ps = (request.portrait_style or "cinematic").strip().lower()
        if _fs_ps == "comic":
            style_prefix = COMIC_STYLE_PRESETS.get(request.story_style, COMIC_STYLE_PRESETS["mature_romantic"])
        else:
            style_prefix = STYLE_PRESETS.get(request.story_style, STYLE_PRESETS["mature_romantic"])
        male_appearance = _character_appearance(request.character)
        male_negative = _character_negative(request.character)
        male_identity_lock = _character_identity_lock(request.character)
        protagonist_identity_lock_final = (
            f"protagonist must strictly match this selected look: {request.protagonist_profile}; "
            "keep consistent facial structure, hairstyle, and vibe; do not switch to another woman."
        )
        _female_label_fs = (request.protagonist_name or "").strip() or "Night Elegance"
        ref_image_line_final = _build_ref_image_line_prompt(
            request.character,
            _female_label_fs,
            f"{request.scene} story finale, cinematic emotional beat",
        )
        style_instruction = (
            "mature romantic, sophisticated tone" if request.story_style == "mature_romantic"
            else "young cute, sweet, lighthearted tone (NOT childish, still respectful)"
        )

        story_prompt = f"""
You are an interactive story writer with a {style_instruction}.

CONTEXT:
- Story mode: {request.story_mode}.
- Scene theme: {request.scene} (keep it consistent; do NOT switch to unrelated activities unless the user sentences clearly imply it).
- Male character: {request.character} (the chosen male lead).
- Male character visual profile (must stay consistent across all images): {male_appearance}.
- Male character strict identity lock: {male_identity_lock}.
- The protagonist is the USER (write in second person 'you', not as a random girl with a new backstory).
- Protagonist visual profile (must stay consistent across all images): {request.protagonist_profile}.

USER SENTENCES (these must be reflected as the 5 beats of the story):
{sentences_str}

TASK:
1) Write ONE coherent short story paragraph (90-130 words) in {request.story_mode} mode that keeps consistency with the 5 beats above.
2) Produce EXACTLY 5 SDXL image prompts (one per beat). CRITICAL — BEAT-TO-IMAGE SEMANTIC LOCK:
   - image_prompts[0] must depict the SPECIFIC action and setting of sentence 1 only (e.g. if sentence 1 is about apology/reschedule → show indoor, man apologizing, nervous or sincere expression).
   - image_prompts[1] must depict the SPECIFIC action and setting of sentence 2 only (e.g. if sentence 2 is about meeting and coffee → show meeting/office context, man handing woman a cup of coffee, friendly).
   - image_prompts[2] must depict sentence 3 only (e.g. restaurant + gift → restaurant interior, man giving woman a gift, polite interaction).
   - image_prompts[3] must depict sentence 4 only (e.g. tennis → tennis court, both in sportswear or casual athletic wear, rackets or playing/practice).
   - image_prompts[4] must depict sentence 5 only (e.g. message/patient → phone or intimate talk, patient gentle mood).
   Each prompt MUST include: (1) CONCRETE LOCATION from that sentence (office, restaurant, tennis court, park, cafe, etc.), (2) KEY OBJECTS if any (coffee cup, gift, tennis racket, phone), (3) the ACTION (apologizing, handing coffee, giving gift, playing tennis, texting/smiling). Do NOT output generic "romantic couple" prompts; each image must be clearly distinguishable by its setting and action so the 5 pictures match the 5 story beats.
   Same style and character design across all 5. Style prefix: "{style_prefix}". Both characters in every image. Protagonist: {request.protagonist_profile}. Male lead identity: {male_identity_lock}. Adults 20-39. Safe and non-explicit.
3) Identify 3–8 key phrases or expressions in the story that are useful for learners. Return as "vocabulary": [{{ "phrase": "...", "explanation": "..." }}].

OUTPUT:
Return ONLY valid JSON:
{{
  "story_text": "...",
  "image_prompts": ["prompt1 for sentence 1 setting+action", "prompt2 for sentence 2 ...", "prompt3 ...", "prompt4 ...", "prompt5 ..."],
  "vocabulary": [{{ "phrase": "exact phrase from story", "explanation": "Short explanation." }}, ...]
}}
"""
        resp = await _openrouter_chat(
            client,
            model=CHAT_MODEL,
            messages=[{"role": "system", "content": story_prompt}],
            response_format={"type": "json_object"},
        )
        story_data = json.loads(resp.choices[0].message.content)

        raw_prompts = story_data.get("image_prompts") or []
        prompts = (raw_prompts + raw_prompts[:5])[:5] if raw_prompts else []
        sentences_for_beats = (request.sentences + [""] * 5)[:5]
        if len(prompts) != 5:
            prompts = []
            for i, s in enumerate(sentences_for_beats):
                prompts.append(
                    f"Depict exactly this moment: {s}. "
                    f"Setting and action must match the sentence. Two people: male lead {request.character} and female protagonist. Safe, non-explicit."
                )

        shot_hints = [
            "wide shot, city/environment visible",
            "medium two-shot, both faces visible",
            "over-shoulder shot, interaction focus",
            "dynamic candid shot, movement visible",
            "close-medium emotional two-shot",
        ]
        final_extra_negative = f"{male_negative}, {NO_TWO_MALES}, {BAD_HANDS}, {ANTI_MUTATION_CURSE}"

        async def _gen_one(idx: int, p: str, sentence_for_beat: str):
            semantic_anchor = (
                f" This image MUST depict this exact moment: \"{sentence_for_beat}\". Setting, location, and action must match."
                if sentence_for_beat.strip() else ""
            )
            full_prompt = (
                f"{style_prefix}. Story mode: {request.story_mode}. Scene theme: {request.scene}. "
                f"Exactly two people only: one man and one woman. The woman (female protagonist) must be clearly visible in frame. "
                f"The only man in frame is the male lead {request.character} ({male_appearance}); "
                f"the only woman in frame is the user protagonist ({request.protagonist_profile}). "
                f"No second man, no two men, no extra male character. Hands relaxed at sides or naturally placed; focus on faces; avoid prominent hand gestures. "
                f"Beat {idx+1}: {p}.{semantic_anchor} {shot_hints[idx % len(shot_hints)]}. "
                f"Clear interaction between the man and the woman, no solo portrait. "
                f"Age lock: both characters must look like adults 20-39; no middle-aged/elderly. "
                f"Identity lock: male lead must remain {request.character} with consistent facial features and hair."
            )
            seed = abs(hash(f"final|{request.scene}|{request.character}|{idx}|{p}")) % 2_000_000_000
            url, nsfw = await _sdxl_generate_image(
                full_prompt,
                seed=seed,
                extra_negative=final_extra_negative,
                is_adult=request.is_adult,
                portrait_style=request.portrait_style or "cinematic",
                ref_image_line=ref_image_line_final,
                ref_male_character=request.character,
                ref_female_name=_female_label_fs,
            )
            return {"url": url, "nsfw_blocked": nsfw}

        results = await asyncio.gather(*[_gen_one(i, prompts[i], sentences_for_beats[i]) for i in range(5)], return_exceptions=True)
        image_urls: list[str | None] = []
        nsfw_any = False
        for r in results:
            if isinstance(r, Exception):
                print(f"⚠️ Final image generation error: {str(r)}")
                image_urls.append(None)
                continue
            image_urls.append(r["url"])
            nsfw_any = nsfw_any or bool(r["nsfw_blocked"])

        # Retry failed slots once so we get 5 images when possible
        for i in range(5):
            if image_urls[i] is not None:
                continue
            try:
                r = await _gen_one(i, prompts[i], sentences_for_beats[i])
                if r.get("url"):
                    image_urls[i] = r["url"]
                    nsfw_any = nsfw_any or bool(r.get("nsfw_blocked"))
            except Exception as e:
                print(f"⚠️ Final image retry error for beat {i+1}: {e}")

        seen_urls = {}
        for i, u in enumerate(image_urls):
            if not u:
                continue
            if u not in seen_urls:
                seen_urls[u] = i
                continue
            retry_prompt = (
                f"{style_prefix}. Story mode: {request.story_mode}. Scene theme: {request.scene}. "
                f"Exactly one man and one woman only: male lead {request.character} ({male_appearance}) and user protagonist ({request.protagonist_profile}). "
                f"No second man, no two men. Beat {i+1} alternative composition, different camera angle, different background layout."
            )
            retry_seed = abs(hash(f"dedupe|{request.scene}|{request.character}|{i}|{u}")) % 2_000_000_000
            retry_url, retry_nsfw = await _sdxl_generate_image(
                retry_prompt,
                seed=retry_seed,
                extra_negative=final_extra_negative,
                is_adult=request.is_adult,
                portrait_style=request.portrait_style or "cinematic",
                ref_image_line=ref_image_line_final,
                ref_male_character=request.character,
                ref_female_name=_female_label_fs,
            )
            if retry_url and retry_url != u:
                image_urls[i] = retry_url
            nsfw_any = nsfw_any or bool(retry_nsfw)

        cover_image_url = next((u for u in image_urls if u), None)
        raw_vocab = story_data.get("vocabulary") or []
        vocabulary = [
            {"phrase": str(v.get("phrase", "")), "explanation": str(v.get("explanation", ""))}
            for v in raw_vocab
            if isinstance(v, dict) and (v.get("phrase") or v.get("explanation"))
        ]
        return {
            "status": "success",
            "story_text": story_data.get("story_text", ""),
            "image_urls": image_urls,
            "cover_image_url": cover_image_url,
            "nsfw_blocked": nsfw_any,
            "vocabulary": vocabulary,
        }
    except Exception as e:
        msg = str(e)
        print(f"❌ API 3 报错: {msg}")
        if _is_openrouter_auth_issue(msg):
            return {
                "status": "failed",
                "error": "OpenRouter authentication failed (401). Please check backend/.env API key.",
            }
        raise HTTPException(status_code=500, detail=msg)
    finally:
        await client.close()

@app.get("/api/debug_outbound_ip")
async def debug_outbound_ip():
    """
    看「后端发 OpenRouter 时」的出口公网 IP（OpenRouter 按这个判地区）。
    浏览器开美国 VPN 不会改这个；必须 OPENROUTER_PROXY 通且 Clash 允许局域网。
    浏览器打开: http://127.0.0.1:8002/api/debug_outbound_ip （端口按你实际后端）
    """
    proxy_url = (
        _clean_env_value(os.getenv("OPENROUTER_PROXY"))
        or _clean_env_value(os.getenv("HTTPS_PROXY"))
        or _clean_env_value(os.getenv("HTTP_PROXY"))
    )
    out: dict[str, Any] = {
        "proxy_configured": bool(proxy_url),
        "hint": "若 ip 仍是中国/香港，OpenRouter 会 403；请开「允许局域网」并确认代理端口对。",
    }
    if proxy_url:
        out["proxy_host"] = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
    try:
        async with (
            httpx.AsyncClient(proxy=proxy_url, timeout=20.0)
            if proxy_url
            else httpx.AsyncClient(timeout=20.0)
        ) as hc:
            r = await hc.get("https://api.ipify.org?format=json")
            out["outbound_ip"] = r.json()
    except Exception as e:
        out["error"] = str(e)
        out["hint"] += " 若 error 为 Connection refused，说明本机连不上代理端口。"
    return out


@app.get("/")
async def root():
    return {"message": "Word Wizard Backend is running!"}
